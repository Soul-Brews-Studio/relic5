#!/usr/bin/env bash
# One picture -> a desk-pet GIF pack: the seven states the pet firmware reads, 96x100 on black.
#
#   tools/make-pack.sh <name> <image.png> [out-dir]      -> <out-dir>/<name>/{manifest.json,*.gif}
#
# The image is one front-facing character. A transparent PNG works best; on an opaque one the
# colour of the top-left corner is keyed out. The states are puppet moves of that one drawing
# (the cheap half of ψ/lab/sprite-one-image in nexus-oracle): idle breathes, busy bounces,
# celebrate jumps, attention hops with a "!" badge, dizzy sways, sleep lies dim with a "z",
# heart floats a heart. Same format as lab/buddy/characters: whole frames, one 128-colour
# palette, no transparent index (the firmware paints transparent pixels black).
set -euo pipefail
NAME="${1:?usage: make-pack.sh <name> <image> [out-dir]}"
SRC="${2:?usage: make-pack.sh <name> <image> [out-dir]}"
OUT_ROOT="${3:-$(cd "$(dirname "$0")/.." && pwd)/workspace/packs}"
[[ "$NAME" =~ ^[a-z0-9_-]{1,23}$ ]] || { echo "❌ $NAME: pack names are lower-case a-z 0-9 - _ (max 23)"; exit 1; }
[ -f "$SRC" ] || { echo "❌ no image at $SRC"; exit 1; }
command -v magick >/dev/null && command -v gifsicle >/dev/null || { echo "❌ needs magick and gifsicle (brew install imagemagick gifsicle)"; exit 1; }

W=96; H=100; COLORS=128
OUT="$OUT_ROOT/$NAME"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$OUT"

# The sprite: background keyed out if the image has no alpha, trimmed, fitted to 80 px (room above for the jumps).
if [ "$(magick "$SRC" -format '%[opaque]' info:)" = "True" ]; then
  BG="$(magick "$SRC" -format '%[pixel:p{0,0}]' info:)"
  magick "$SRC" -alpha set -fuzz 4% -fill none -draw "alpha 0,0 floodfill" \
    -draw "alpha %[fx:w-1],0 floodfill" "$T/keyed.png" 2>/dev/null \
    || magick "$SRC" -fuzz 4% -transparent "$BG" "$T/keyed.png"
else
  cp "$SRC" "$T/keyed.png"
fi
magick "$T/keyed.png" -trim +repage -filter Lanczos -resize 80x80 "$T/sprite.png"
SW=$(magick "$T/sprite.png" -format %w info:); SH=$(magick "$T/sprite.png" -format %h info:)
BODY="$(magick "$T/sprite.png" -background black -alpha remove -resize 1x1\! -format '#%[hex:p{0,0}]' info: | cut -c1-7)"
echo "🐾 $NAME: sprite ${SW}x${SH}, body $BODY"

# frame <out> <scale-x%> <scale-y%> <lift px> <rotate deg> <dim 0|1> [extra -draw ...]
frame() {
  local out="$1" sx="$2" sy="$3" lift="$4" rot="$5" dim="$6"; shift 6
  local y=$(( 6 + lift ))
  magick -size ${W}x${H} xc:black \
    \( "$T/sprite.png" -resize "${sx}%x${sy}%"\! -background none -rotate "$rot" \
       $( [ "$dim" = 1 ] && echo "-fill black -colorize 45%" ) \) \
    -gravity south -geometry "+0+${y}" -composite -gravity northwest "$@" "$out"
}
heart_at() {   # heart_at <cx> <cy>  -> -draw args for a 14 px heart centred there
  local cx=$1 cy=$2
  echo "fill #ff3b5c circle $((cx-3)),$cy $((cx)),$cy circle $((cx+3)),$cy $((cx+6)),$cy polygon $((cx-7)),$((cy+1)) $((cx+7)),$((cy+1)) $cx,$((cy+9))"
}
gif() {   # gif <state> <delay cs> frames...
  local state="$1" delay="$2"; shift 2
  magick -delay "$delay" -loop 0 "$@" -background black -alpha remove -alpha off "$T/$state.gif"
  gifsicle --colors "$COLORS" -o "$T/$state.gif" "$T/$state.gif"
  gifsicle --unoptimize --no-transparent -o "$OUT/$state.gif" "$T/$state.gif"
}

PI=3.14159265
wave() { python3 -c "import math;print(round($1*math.sin(2*$PI*$2/$3)))"; }

# idle: slow breath (height 100 -> 96 %)
f=(); for i in 0 1 2 3 4 5 6 7; do d=$(wave 2 $i 8); frame "$T/i$i.png" 100 $((98+d)) 0 0 0; f+=("$T/i$i.png"); done; gif idle 12 "${f[@]}"
# busy: quick bounce with a squash on landing
f=(); for i in 0 1 2 3 4 5 6 7; do l=$(python3 -c "import math;print(round(8*abs(math.sin($PI*$i/4))))"); s=$([ "$l" -lt 2 ] && echo 94 || echo 100); frame "$T/b$i.png" 102 $s "$l" 0 0; f+=("$T/b$i.png"); done; gif busy 6 "${f[@]}"
# celebrate: one big jump with a spin of the head
f=(); for i in $(seq 0 11); do l=$(python3 -c "import math;print(round(12*math.sin($PI*$i/11)))"); r=$(python3 -c "import math;print(round(10*math.sin(2*$PI*$i/11)))"); frame "$T/c$i.png" 100 100 "$l" "$r" 0; f+=("$T/c$i.png"); done; gif celebrate 7 "${f[@]}"
# attention: two hops and a blinking yellow "!" badge, top right
f=(); for i in 0 1 2 3 4 5 6 7; do l=$(python3 -c "import math;print(round(7*abs(math.sin($PI*$i/4))))")
  if [ $((i % 2)) -eq 0 ]; then badge=(-fill '#ffd400' -draw "circle 82,13 82,4" -fill black -draw "rectangle 81,7 83,15" -draw "rectangle 81,17 83,19"); else badge=(); fi
  frame "$T/a$i.png" 100 100 "$l" 0 0 "${badge[@]}"; f+=("$T/a$i.png"); done; gif attention 10 "${f[@]}"
# dizzy: sway +-12 degrees
f=(); for i in 0 1 2 3 4 5 6 7; do r=$(wave 12 $i 8); frame "$T/d$i.png" 100 100 0 "$r" 0; f+=("$T/d$i.png"); done; gif dizzy 10 "${f[@]}"
# sleep: lying low and dim, breathing, a "z" drifting up
f=(); for i in 0 1 2 3 4 5 6 7; do d=$(wave 2 $i 8); zy=$((40 - i * 3))
  frame "$T/s$i.png" 104 $((70+d)) -4 0 1 -fill '#9fb4ff' -font "/System/Library/Fonts/Supplemental/Arial Bold.ttf" -pointsize $((10 + i / 2)) -annotate "+$((70 + i))+$zy" z
  f+=("$T/s$i.png"); done; gif sleep 18 "${f[@]}"
# heart: idle with a heart rising over the head
f=(); for i in 0 1 2 3 4 5 6 7; do cy=$((30 - i * 3)); frame "$T/h$i.png" 100 100 0 0 0 -draw "$(heart_at 72 $cy)"; f+=("$T/h$i.png"); done; gif heart 10 "${f[@]}"

cat > "$OUT/manifest.json" <<EOF
{
  "name": "$NAME",
  "colors": { "body": "$BODY", "bg": "#000000", "text": "#FFFFFF", "textDim": "#808080", "ink": "#000000" },
  "states": {
    "sleep": "sleep.gif",
    "idle": ["idle.gif"],
    "busy": "busy.gif",
    "attention": "attention.gif",
    "celebrate": "celebrate.gif",
    "dizzy": "dizzy.gif",
    "heart": "heart.gif"
  }
}
EOF
for g in "$OUT"/*.gif; do
  if gifsicle --info "$g" | grep -q transparent; then echo "❌ $g has transparency"; exit 1; fi
done
echo "✅ $OUT  $(du -sk "$OUT" | cut -f1) KB  ($(ls "$OUT" | tr '\n' ' '))"
