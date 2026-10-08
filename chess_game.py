"""Chess at his desk (#17): a local board, a small opponent, and his brain model picking among candidate moves.

    python-chess (pure Python, no engine binary) keeps the board and the rules; nothing goes online, no accounts.
- The opponent is a depth-2 minimax (its move, then his best reply) on a material + centre score, with random
  tie-breaks: a weak, predictable club-player-at-a-glance, not an engine.
- On his turn a simple move scorer (the same score, one ply) ranks the legal moves and keeps the top CANDIDATES (5).
  Those are the options of the brain vote (brain_vote.vote): each move is tagged with the networks it would mostly
  drive, from what the scorer sees on the board (a capture -> reward, a check -> attention and salience, a piece left
  where it can be taken for free -> threat, castling -> control), and the brain model picks one.
- Games go to /data/chess.jsonl (state_io.append_jsonl), one row per game.
The card says what this is: his brain model picks among 5 candidate moves from a simple move scorer.
"""
import random
import time

import chess

CANDIDATES = 5
MAX_PLIES = 160                  # a game this long is left unfinished (80 moves each)
VALUES = {chess.PAWN: 1.0, chess.KNIGHT: 3.0, chess.BISHOP: 3.2, chess.ROOK: 5.0, chess.QUEEN: 9.0, chess.KING: 0.0}
CENTRE = 0.08                    # per piece standing on one of the 4 centre squares (16 for the wider centre: half)
TIE = 1e-6
MATE = 1000.0
CARD = "his brain model picks among 5 candidate moves from a simple move scorer"
NOTE = ("The candidate moves come from a simple move scorer (material and the centre, one move ahead); the opponent "
        "is a small depth-2 search. His brain model is shown the 5 candidates as stimuli and its simulated response "
        "picks one.")
CENTER4 = chess.SquareSet([chess.D4, chess.E4, chess.D5, chess.E5])
CENTER16 = chess.SquareSet(chess.BB_CENTER | 0x00003C3C3C3C0000)


def score(board, color):
    """Material + centre for `color` (positive: better for `color`); mate and draws scored as such."""
    if board.is_checkmate():
        return -MATE if board.turn == color else MATE
    if board.is_stalemate() or board.is_insufficient_material():
        return 0.0
    s = 0.0
    for sq, p in board.piece_map().items():
        v = VALUES[p.piece_type] + (CENTRE if sq in CENTER4 else CENTRE / 2 if sq in CENTER16 else 0.0)
        s += v if p.color == color else -v
    return s


def hanging(board, move):
    """After `move`, can the moved piece be taken where it stands by a cheaper piece or for free (no defender)?"""
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type == chess.KING:
        return False
    after = board.copy(stack=False)
    after.push(move)
    to = move.to_square
    attackers = after.attackers(not piece.color, to)
    if not attackers:
        return False
    cheapest = min(VALUES[after.piece_type_at(a)] for a in attackers)
    value = VALUES[after.piece_type_at(to) or piece.piece_type]
    return not after.attackers(piece.color, to) or cheapest < value


def features(board, move):
    """What the scorer sees about one move (no look-ahead beyond the move itself)."""
    captured = board.piece_at(move.to_square)
    gain = VALUES[captured.piece_type] if captured else (1.0 if board.is_en_passant(move) else 0.0)
    return {"capture": gain, "check": board.gives_check(move), "castle": board.is_castling(move),
            "promotion": bool(move.promotion), "hanging": hanging(board, move)}


def networks(f):
    """Move features -> {network: 0..1}, the stimulus the brain vote tries out (same form as eyes.py options)."""
    n = {"visual": 0.3, "attention": 0.3}
    if f["capture"]:
        n["reward"] = min(1.0, 0.3 + f["capture"] / 6)
    if f["promotion"]:
        n["reward"] = max(n.get("reward", 0.0), 0.9)
    if f["check"]:
        n["attention"], n["salience"] = 0.7, 0.5
    if f["castle"]:
        n["control"] = 0.5
    if f["hanging"]:
        n["fear"] = 0.6
    if len(n) == 2:                                   # a quiet move: mostly the hand moving a piece
        n["somatomotor"] = 0.3
    return n


def candidates(board, rng=None, k=CANDIDATES):
    """The scorer's top k legal moves for the side to move, as brain-vote options (best first)."""
    rng = rng or random.Random()
    me = board.turn
    moves = list(board.legal_moves)
    rng.shuffle(moves)                                # equal scores: a random order, not the generator's
    scored = []
    for m in moves:
        board.push(m)
        s = score(board, me)
        board.pop()
        scored.append((s, m))
    scored.sort(key=lambda x: -x[0])
    out = []
    for s, m in scored[:k]:
        f = features(board, m)
        out.append({"action": "chess_move", "target": m.uci(), "label": board.san(m), "networks": networks(f),
                    "score": round(s, 2), "features": {k_: v for k_, v in f.items() if v}})
    return out


def opponent_move(board, rng=None):
    """Depth-2 minimax for the side to move: its move, then the reply that is best for the other side. Ties (within
    1e-6) are broken at random."""
    rng = rng or random.Random()
    me = board.turn
    best, best_moves = None, []
    for m in list(board.legal_moves):
        board.push(m)
        if board.is_game_over(claim_draw=False):
            v = score(board, me)
        else:
            v = None
            for r in list(board.legal_moves):
                board.push(r)
                s = score(board, me)
                board.pop()
                v = s if v is None or s < v else v
        board.pop()
        if best is None or v > best + TIE:
            best, best_moves = v, [m]
        elif abs(v - best) <= TIE:
            best_moves.append(m)
    return rng.choice(best_moves) if best_moves else None


def result_of(board, his_color):
    """('won' | 'lost' | 'draw' | None, reason) from his side."""
    o = board.outcome(claim_draw=True)
    if o is None:
        return None, None
    reason = o.termination.name.lower().replace("_", " ")
    if o.winner is None:
        return "draw", reason
    return ("won" if o.winner == his_color else "lost"), reason


class Game:
    """One game at the desk. He plays `color`; `rng` breaks the opponent's ties and orders equal candidates."""

    def __init__(self, t, color=None, rng=None):
        self.rng = rng or random.Random()
        self.board = chess.Board()
        self.color = color if color is not None else self.rng.choice([chess.WHITE, chess.BLACK])
        self.started = t
        self.sans = []
        self.votes = []                              # his decisions: options, p, the pick (the card)
        self.result = self.reason = None
        self.next_at = 0.0                           # wall time of the next move (paced by the server)

    @property
    def his_turn(self):
        return self.board.turn == self.color and not self.over

    @property
    def over(self):
        return self.result is not None

    def push(self, move):
        """Play a legal move (a chess.Move or UCI text); refuses anything illegal. Returns its SAN."""
        m = chess.Move.from_uci(move) if isinstance(move, str) else move
        if m not in self.board.legal_moves:
            raise ValueError(f"illegal move {m.uci()} in {self.board.fen()}")
        san = self.board.san(m)
        self.board.push(m)
        self.sans.append(san)
        self.result, self.reason = result_of(self.board, self.color)
        if self.result is None and len(self.sans) >= MAX_PLIES:
            self.result, self.reason = "unfinished", "move limit"
        return san

    def candidates(self):
        """Safe in a worker thread: it searches a copy, so the board the pages read never changes under them."""
        return candidates(self.board.copy(stack=False), self.rng)

    def opponent(self):
        return opponent_move(self.board.copy(stack=False), self.rng)

    def stop(self, why="he got up"):
        if self.result is None:
            self.result, self.reason = "unfinished", why

    def record(self, t):
        """The /data/chess.jsonl row."""
        return {"t": round(t), "started": round(self.started), "wall": round(time.time()),
                "color": "white" if self.color == chess.WHITE else "black", "result": self.result,
                "reason": self.reason, "plies": len(self.sans), "moves": " ".join(self.sans),
                "his_moves_voted": len(self.votes), "fen": self.board.fen()}

    def public(self):
        """The board for the pages: FEN, his colour, moves, the last vote (the card)."""
        last = self.board.peek().uci() if self.board.move_stack else None
        return {"fen": self.board.fen(), "color": "white" if self.color == chess.WHITE else "black",
                "turn": "his" if self.board.turn == self.color else "opponent", "moves": self.sans[-40:],
                "plies": len(self.sans), "last": last, "check": self.board.is_check(), "result": self.result,
                "reason": self.reason, "vote": self.votes[-1] if self.votes else None, "card": CARD}
