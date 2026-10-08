# Real food in the room (#63, part 2)

The owner's second report (23:20 Tokyo): "He isn't eating anything… make real food, courier bags, everything must be
real". The title said "is eating bread at the table" while the reason said "eats the meal at the table", and there was
no food anywhere. Part 1 (#82) is the motion; this part is the food.

## What he orders, and the labels (`life.py`)
A small change, as the issue allows (LABEL and the dish field). #61's needs-first logic is untouched.
- **When he starts `order_food`, he picks a dish:** ramen, sushi, pizza, curry or bento.
  - It is a viewer's wish if one was heard in the last sim hour ("sushi", "pizza"…), otherwise random.
  - The pick uses its own random stream (seeded from the time), so the needs logic's draws, and #61's seeded tests,
    stay exactly as they were.
- **It travels with the order:**
  - `order` while ordering (the phone's order screen shows "Your order: 1 × ramen");
  - `delivery.dish` and `courier.dish` while the courier rides;
  - `food_items` once delivered.
- **The konbini adds an onigiri or a konbini bento** to `food_items`.
- **Eating sets `eating`** to the first waiting item, or to `bread`.
- **The labels name it:**
  - "ordering sushi on the phone";
  - "eating ramen from the delivery";
  - "eating an onigiri from the konbini";
  - "eating bread at the table".

  The reason also names it: "hungry: eats the ramen at the table".
- **Tests:**
  - `test_dish_follows_the_order`: a wish → the dish → the courier → `food_items` → the label.
  - `test_dish_without_a_wish`.
  - One #61 assertion changes. It expected the konbini meal to read "eating bread at the table", which is exactly the
    mismatch the owner reported; it now expects the konbini label. The whole suite passes.

## In the room (`web/room.html`, `web/room/food.glb`)
- **Models:** Kenney's Food Kit (CC0), packed by `room_build/build_food.mjs` into `food.glb` (84 KB, one shared
  palette texture). See `web/room/CREDITS.md`.
- **Delivery:**
  - The courier's bag appears in the doorway when he opens the door; a pizza comes in its own box.
  - He carries it to the desk, and it stays there while the meal waits.
- **Bakery and konbini:**
  - He comes home with the shop's bag in his hand (brown paper from the bakery, white from the konbini) and puts it on
    the desk.
  - The bakery bag stays while he has bread, and looks emptier when one roll is left.
- **Eating:**
  - The bag opens to the dish on the desk in front of him: the chair rolls 12 cm left, to the dish left of the keyboard.
    The dishes are a ramen bowl, a curry bowl, a sushi tray, an open pizza box, or a bento.
  - The right hand goes from the dish to his mouth at a natural pace (picking, lifting, a bite, chewing nods). It
    carries chopsticks with a morsel, a sushi piece, or a pizza slice that shrinks over three bites. The left hand
    steadies the bowl.
  - Bread (a croissant) and an onigiri are eaten from the hand and get smaller.
- **The dish empties:**
  - sushi pieces go one by one;
  - pizza slices go one by one;
  - the ramen and the curry sink and leave an empty bowl;
  - the bento's compartments empty.
- **Afterwards:** before he gets up he takes the empty dish, carries it level, crouches at the end of the desk (the bin
  is under it) and drops it in.
- **The drink:** his bottle of tea moved to the right of the keyboard (the dish takes the left); he drinks with his
  right hand.

## Evidence (`food/` here)
- **Frame strips and WebMs.** The whole delivery cycle is ramen: order on the phone → the doorbell → the door → the bag
  → the desk → eating (one frame every 2 s) → the empty bowl → the bin. Also pizza and sushi emptying, the bakery
  return and bread, and the konbini return and an onigiri.
- **Screenshots** of the whole page at 1280 and 390 px: `screens/`. They show eating ramen, ordering sushi (the order
  screen) and eating pizza, with the labels.
- **Penetration:** 0 bed and 0 chair vertices, in every captured case and in a food-cycle sweep (21 activity
  changes, 2 seeds). See `penetration_food.txt`.
