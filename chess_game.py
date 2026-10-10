"""Chess at his desk (#17): a local board, a small opponent, and his brain model picking among candidate moves.

    python-chess (pure Python, no engine binary) keeps the board and the rules; nothing goes online, no accounts.
- One small search (`search`) ranks the legal moves for either side: each move is worth the worst case over the
  other side's replies (depth 2) on a material + centre score, with positional tie-breaks (developed minors, castling,
  mobility, a check or a capture). A capturing reply is extended by the best recapture on that square, so a defended
  piece that is merely attacked does not read as lost. Equal values keep a random order.
- On his turn the search's top CANDIDATES (5) within MARGIN of the best are the options of the brain vote
  (brain_vote.vote): each move is tagged with the networks it would mostly drive, from what the scorer sees on the
  board (a capture -> reward, a check -> attention and salience, a piece left where it can be taken for free -> threat,
  castling -> control), and the brain model picks one. The vote does not read the value: the ranking is the only thing
  keeping a hung queen off the card, so a move the search sees losing material is not offered while a better one is.
- A move back into a position of this game costs the side that is ahead (REPEAT), and a king left with only pawns is
  driven to the edge (MOPUP), so won games end in mate rather than a shuffle or the move limit.
- The opponent is uneven: it plays the search's move with probability `level` (LEVEL by default, 0.85), otherwise a
  random capture or a random one of the 5 best one-ply moves: a club player at a glance, who also blunders. `level_for`
  nudges `level` from the W/D/L of the last 20 games so he neither wins nor loses them all.
- Games go to /data/chess.jsonl (state_io.append_jsonl), one row per game.
The card says what this is: his brain model picks among 5 candidate moves from a simple move scorer.
"""
import random
import time

import chess

CANDIDATES = 5
MARGIN = 2.0                     # a candidate this far below the best move (about a minor piece) is not offered
MAX_PLIES = 160                  # a game this long is left unfinished (80 moves each)
VALUES = {chess.PAWN: 1.0, chess.KNIGHT: 3.0, chess.BISHOP: 3.2, chess.ROOK: 5.0, chess.QUEEN: 9.0, chess.KING: 0.0}
CENTRE = 0.08                    # per piece standing on one of the 4 centre squares (16 for the wider centre: half)
DEVELOPED = 0.05                 # per knight or bishop off its back rank
CASTLED = 0.3                    # the king tucked in behind a castled rook (or no longer able to castle, same square)
MOBILITY = 0.02                  # per square a knight, bishop, rook or queen can go to
ACTIVE = 0.2                     # a check or a capture over a quiet move of the same material value
MOPUP = 0.1                      # an enemy left with king and pawns: its king driven to the edge and approached
REPEAT = 0.6                     # per earlier visit of the position a move returns to, while clearly ahead...
AHEAD = 2.0                      # ...by this much (no shuffling into a repetition when winning; a level game may)
TIE = 1e-6
MATE = 1000.0
LEVEL = 0.85                     # how often the opponent plays the search's move (else a capture or a one-ply pick)
LEVEL_GAIN = 0.5                 # ...nudged by (wins - losses) / games over the last LEVEL_GAMES games
LEVEL_GAMES = 20
LEVEL_RANGE = (0.5, 1.0)
CARD = "his brain model picks among 5 candidate moves from a simple move scorer"
NOTE = ("The candidate moves come from a simple move scorer (material and the centre, two moves ahead: his move and "
        "the reply); the opponent is a small search that also blunders. His brain model is shown up to 5 candidates "
        "as stimuli and its simulated response picks one.")
CENTER4 = chess.SquareSet([chess.D4, chess.E4, chess.D5, chess.E5])
CENTER16 = chess.SquareSet(chess.BB_CENTER | 0x00003C3C3C3C0000)
BACK_RANK = {chess.WHITE: chess.BB_RANK_1, chess.BLACK: chess.BB_RANK_8}
CASTLE_SQ = {chess.WHITE: (chess.G1, chess.C1), chess.BLACK: (chess.G8, chess.C8)}
MINORS = chess.KNIGHT, chess.BISHOP
MOVERS = chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN


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


def positional(board, color):
    """Small tie-breaks for `color` on the position as it stands: development, castling, mobility, the mop-up."""
    s = 0.0
    own = board.occupied_co[color]
    for pt in MINORS:
        s += DEVELOPED * chess.popcount(board.pieces_mask(pt, color) & ~BACK_RANK[color])
    for pt in MOVERS:
        for sq in chess.scan_forward(board.pieces_mask(pt, color)):
            s += MOBILITY * chess.popcount(board.attacks_mask(sq) & ~own)
    king = board.king(color)
    if king is not None and king in CASTLE_SQ[color] and not board.has_castling_rights(color):
        s += CASTLED
    their, heavy = board.occupied_co[not color], board.rooks | board.queens
    if king is not None and not their & heavy and own & heavy:     # my rook or queen against no rook or queen: mate it
        k2 = board.king(not color)
        s += MOPUP * (chess.square_distance(k2, chess.E4) + chess.square_distance(k2, chess.D5)
                      - chess.square_distance(king, k2))
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
    if not attackers or after.is_checkmate():                            # nothing is taken after mate
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


def _leaf(board, me, to):
    """Material after a reply; a capturing reply (`to` is its square) is answered by the best recapture there."""
    v = score(board, me)
    if to is not None and board.turn == me:
        for c in board.generate_legal_captures(chess.BB_ALL, chess.BB_SQUARES[to]):
            board.push(c)
            s = score(board, me)
            board.pop()
            v = s if s > v else v
    return v


def position_key(board):
    """The position without the move counters: what a repetition repeats."""
    return " ".join(board.fen().split()[:4])


def search(board, rng=None, seen=None):
    """Depth-2 ranking of the legal moves for the side to move: [(value, move)], best first. A move is worth the
    minimum of `score` over the other side's replies (plus `positional` and ACTIVE for the move itself); ties within
    1e-6 keep a shuffled order, so equal moves come in a random order, not the generator's. `seen` ({position_key:
    visits} of the game so far) costs a move that returns to a known position while ahead: the side that is winning
    does not shuffle into a threefold repetition (a level game may: a draw is a finished game)."""
    rng = rng or random.Random()
    me = board.turn
    moves = list(board.legal_moves)
    rng.shuffle(moves)
    out = []
    for m in moves:
        active = ACTIVE if board.is_capture(m) or board.gives_check(m) else 0.0
        board.push(m)
        if board.is_game_over(claim_draw=False):
            v = score(board, me)
        elif seen and seen.get(position_key(board)) and score(board, me) >= AHEAD:
            v = score(board, me) - REPEAT * seen[position_key(board)]
        else:
            v = None
            for r in list(board.legal_moves):
                to = r.to_square if board.is_capture(r) else None
                board.push(r)
                s = _leaf(board, me, to)
                board.pop()
                v = s if v is None or s < v else v
            v += positional(board, me) + active
        board.pop()
        out.append((v, m))
    out.sort(key=lambda x: -x[0])
    return out


def candidates(board, rng=None, k=CANDIDATES, seen=None):
    """The search's top k legal moves within MARGIN of the best, as brain-vote options (best first)."""
    ranked = search(board, rng, seen)
    out = []
    for v, m in ranked[:k]:
        if out and v < ranked[0][0] - MARGIN:
            break
        f = features(board, m)
        out.append({"action": "chess_move", "target": m.uci(), "label": board.san(m), "networks": networks(f),
                    "score": round(v, 2), "features": {k_: v_ for k_, v_ in f.items() if v_}})
    return out


def opponent_move(board, rng=None, level=LEVEL, seen=None):
    """The opponent's move: the search's best with probability `level`, otherwise a random capture (half the time,
    when there is one) or a random one of the 5 best one-ply moves: a player who also blunders."""
    rng = rng or random.Random()
    ranked = search(board, rng, seen)
    if not ranked:
        return None
    if rng.random() < level or len(ranked) == 1:
        return ranked[0][1]
    captures = [m for _, m in ranked if board.is_capture(m)]
    if captures and rng.random() < 0.5:
        return rng.choice(captures)
    me = board.turn
    shallow = []
    for _, m in ranked:
        board.push(m)
        shallow.append((score(board, me), m))
        board.pop()
    shallow.sort(key=lambda x: -x[0])
    return rng.choice(shallow[:CANDIDATES])[1]


def level_for(rows, base=LEVEL):
    """The opponent's `level` from the last LEVEL_GAMES chess.jsonl rows: up when he has been winning, down when he
    has been losing, so the record over 20 games stays mixed."""
    rows = [r for r in rows if r.get("result") in ("won", "lost", "draw")][-LEVEL_GAMES:]
    if not rows:
        return base
    diff = sum(r["result"] == "won" for r in rows) - sum(r["result"] == "lost" for r in rows)
    lo, hi = LEVEL_RANGE
    return min(hi, max(lo, base + LEVEL_GAIN * diff / max(len(rows), 10)))


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
    """One game at the desk. He plays `color`; `rng` breaks the opponent's ties and orders equal candidates; `level`
    is how often the opponent plays its best move (see opponent_move)."""

    def __init__(self, t, color=None, rng=None, level=LEVEL):
        self.rng = rng or random.Random()
        self.board = chess.Board()
        self.color = color if color is not None else self.rng.choice([chess.WHITE, chess.BLACK])
        self.level = level
        self.seen = {position_key(self.board): 1}    # positions of this game, for the repetition penalty
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
        key = position_key(self.board)
        self.seen[key] = self.seen.get(key, 0) + 1
        self.result, self.reason = result_of(self.board, self.color)
        if self.result is None and len(self.sans) >= MAX_PLIES:
            self.result, self.reason = "unfinished", "move limit"
        return san

    def candidates(self):
        """Safe in a worker thread: it searches a copy, so the board the pages read never changes under them."""
        return candidates(self.board.copy(stack=False), self.rng, seen=dict(self.seen))

    def opponent(self):
        return opponent_move(self.board.copy(stack=False), self.rng, self.level, seen=dict(self.seen))

    def stop(self, why="he got up"):
        if self.result is None:
            self.result, self.reason = "unfinished", why

    def record(self, t):
        """The /data/chess.jsonl row."""
        return {"t": round(t), "started": round(self.started), "wall": round(time.time()),
                "color": "white" if self.color == chess.WHITE else "black", "result": self.result,
                "reason": self.reason, "plies": len(self.sans), "moves": " ".join(self.sans),
                "his_moves_voted": len(self.votes), "level": round(self.level, 2), "fen": self.board.fen()}

    def public(self):
        """The board for the pages: FEN, his colour, moves, the last vote (the card)."""
        last = self.board.peek().uci() if self.board.move_stack else None
        return {"fen": self.board.fen(), "color": "white" if self.color == chess.WHITE else "black",
                "turn": "his" if self.board.turn == self.color else "opponent", "moves": self.sans[-40:],
                "plies": len(self.sans), "last": last, "check": self.board.is_check(), "result": self.result,
                "reason": self.reason, "vote": self.votes[-1] if self.votes else None, "card": CARD}
