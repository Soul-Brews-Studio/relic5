// neo-mood: the desk pet as neo, the fleet coordinator, showing how neo feels about the fleet right now
// (Nat, 2026-10-24: "add wasm app show neo mood"). Built with esp32-oracle's pet-sdk to WebAssembly and baked
// into the neo firmware as its autorun app, or sent alone over Bluetooth (a few KB, about 1 s).
//
// neo's moods, from what neo does: it tends panes (herdr sessions) and answers the agents that wait.
//   agents waiting   -> attention  "3 need neo"         neo's job: answer them
//   agents running   -> busy       "tending 4 panes"
//   all quiet        -> idle       "fleet calm", then after a minute -> sleep "zzz, all done"
//   the last waiting agent answered -> the heart and a blip up: "all answered"
//   a tap            -> the heart, and a line from neo's notes in turn (its most-used words)
// The fleet counts come from OraclePet (on_fleet), the same feed fleet-mood.c uses.
#include "pet.h"

static int last_waiting, quiet_since, line_at;
static const char *lines[] = { "look before", "never guess", "hold the line", "maw hey", "retro done", "panes tended" };

static void say_line(void)
{
    pet_caption(lines[line_at]);
    line_at = (line_at + 1) % (int)(sizeof lines / sizeof lines[0]);
}

PET_EXPORT("on_start") void on_start(void)
{
    pet_pack("neo");                 // neo's own sprite, when the neo pack is on the pet
    pet_status("neo: mood");
    pet_show(PET_IDLE);
    pet_caption("neo is here");
    quiet_since = pet_millis();
}

PET_EXPORT("on_fleet") void on_fleet(int total, int running, int waiting)
{
    char b[24]; int at = 0;
    int now = pet_millis();
    if (waiting > 0) {
        pet_show(PET_ATTENTION);
        pet_put_int(b, &at, waiting); pet_put_str(b, &at, waiting == 1 ? " needs neo" : " need neo");
    } else if (running > 0) {
        pet_show(PET_BUSY);
        pet_put_str(b, &at, "tending "); pet_put_int(b, &at, running); pet_put_str(b, &at, running == 1 ? " pane" : " panes");
    } else if (now - quiet_since > 60000) {
        pet_show(PET_SLEEP);
        pet_put_str(b, &at, "zzz, all done");
    } else {
        pet_show(PET_IDLE);
        pet_put_str(b, &at, total ? "fleet calm" : "no agents yet");
    }
    if (waiting || running) quiet_since = now;
    if (last_waiting > 0 && waiting == 0) { pet_react(); pet_sound(PET_BLIP_UP); at = 0; pet_put_str(b, &at, "all answered"); }
    last_waiting = waiting;
    pet_caption(b);
}

PET_EXPORT("on_tap") void on_tap(int x, int y)
{
    (void)x; (void)y;
    pet_react();
    say_line();
}
