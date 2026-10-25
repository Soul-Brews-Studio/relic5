// The 3D map: every session a point, after lanceglass's Atlas 3D (ui/src/VectorMap3D.tsx, 2026-09-01) and the old
// Studio's Planets. three.js points with a colour per repo, orbit controls (drag to turn, wheel to zoom, right-drag to
// pan), a raycaster for hover and click. Loaded on its own (lazy) so the rest of the hub never carries three.js.
import { useEffect, useRef } from "react";
import { BufferAttribute, BufferGeometry, CanvasTexture, Color, PerspectiveCamera, Points, PointsMaterial, Raycaster, Scene, Vector2, WebGLRenderer } from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import type { MapPoint } from "./MapView";

/** A soft round sprite, so points read as dots, not squares. */
function dot(): CanvasTexture {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d")!;
  const r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  r.addColorStop(0, "rgba(255,255,255,1)"); r.addColorStop(0.55, "rgba(255,255,255,.9)"); r.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = r; g.beginPath(); g.arc(32, 32, 32, 0, Math.PI * 2); g.fill();
  return new CanvasTexture(c);
}

export default function Map3D({ points, colors, dim, selected, onHover, onSelect, spin }: {
  points: MapPoint[]; colors: string[]; dim: boolean[]; selected: number; onHover: (i: number, x: number, y: number) => void;
  onSelect: (i: number) => void; spin: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const api = useRef<{ paint: () => void; select: (i: number) => void; spin: (on: boolean) => void } | null>(null);
  const live = useRef({ colors, dim, onHover, onSelect });
  live.current = { colors, dim, onHover, onSelect };

  useEffect(() => {
    const el = host.current!;
    const renderer = new WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    el.appendChild(renderer.domElement);
    const scene = new Scene();
    const camera = new PerspectiveCamera(50, 1, 0.01, 100);
    camera.position.set(0, 0, 3.2);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true; controls.dampingFactor = 0.08; controls.autoRotateSpeed = 0.6;

    const pos = new Float32Array(points.length * 3), col = new Float32Array(points.length * 3);
    const target = new Float32Array(points.length * 3);
    points.forEach((p, i) => { target[i * 3] = p.x; target[i * 3 + 1] = p.y; target[i * 3 + 2] = p.z; });
    // the points fly out from the centre to where they belong (900 ms, ease-out), unless motion is turned down
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches, t0 = performance.now(), DUR = 900;
    let growing = !still;
    pos.set(still ? target : target.map(v => v * 0.02));
    const geo = new BufferGeometry();
    geo.setAttribute("position", new BufferAttribute(pos, 3));
    geo.setAttribute("color", new BufferAttribute(col, 3));
    const sprite = dot();
    const mat = new PointsMaterial({ size: 0.045, vertexColors: true, map: sprite, transparent: true, alphaTest: 0.05, depthWrite: false, sizeAttenuation: true });
    const cloud = new Points(geo, mat);
    cloud.frustumCulled = false;   // its bounds change while the points fly out
    scene.add(cloud);
    // the selected session: one bigger white point drawn on top
    const selGeo = new BufferGeometry();
    selGeo.setAttribute("position", new BufferAttribute(new Float32Array(3), 3));
    const sel = new Points(selGeo, new PointsMaterial({ size: 0.14, color: 0xffffff, map: sprite, transparent: true, depthTest: false }));
    sel.visible = false;
    scene.add(sel);

    const paint = () => {
      const c = new Color();
      live.current.colors.forEach((hex, i) => {
        c.set(hex);
        const k = live.current.dim[i] ? 0.16 : 1;
        col[i * 3] = c.r * k; col[i * 3 + 1] = c.g * k; col[i * 3 + 2] = c.b * k;
      });
      geo.attributes.color.needsUpdate = true;
    };
    paint();
    const select = (i: number) => {
      sel.visible = i >= 0;
      if (i >= 0) { const a = selGeo.attributes.position as BufferAttribute; a.setXYZ(0, points[i].x, points[i].y, points[i].z); a.needsUpdate = true; }
    };
    api.current = { paint, select, spin: on => { controls.autoRotate = on; } };

    const ray = new Raycaster(); ray.params.Points = { threshold: 0.03 };
    const mouse = new Vector2();
    const pick = (e: PointerEvent) => {
      const r = renderer.domElement.getBoundingClientRect();
      mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(mouse, camera);
      const hit = ray.intersectObject(cloud).find(h => h.index != null && !live.current.dim[h.index]);
      return { i: hit?.index ?? -1, x: e.clientX - r.left, y: e.clientY - r.top };
    };
    let down = { x: 0, y: 0 };
    const move = (e: PointerEvent) => { const p = pick(e); live.current.onHover(p.i, p.x, p.y); renderer.domElement.style.cursor = p.i >= 0 ? "pointer" : "grab"; };
    const press = (e: PointerEvent) => { down = { x: e.clientX, y: e.clientY }; };
    const up = (e: PointerEvent) => { if (Math.hypot(e.clientX - down.x, e.clientY - down.y) < 4) { const p = pick(e); if (p.i >= 0) live.current.onSelect(p.i); } };
    const leave = () => live.current.onHover(-1, 0, 0);
    renderer.domElement.addEventListener("pointermove", move);
    renderer.domElement.addEventListener("pointerdown", press);
    renderer.domElement.addEventListener("pointerup", up);
    renderer.domElement.addEventListener("pointerleave", leave);

    const size = () => { const w = el.clientWidth, h = el.clientHeight; renderer.setSize(w, h, false); renderer.domElement.style.width = "100%"; renderer.domElement.style.height = "100%"; camera.aspect = w / Math.max(h, 1); camera.updateProjectionMatrix(); };
    const ro = new ResizeObserver(size); ro.observe(el); size();
    let raf = 0;
    const tick = () => {
      if (growing) {
        const t = Math.min(1, (performance.now() - t0) / DUR), k = 1 - Math.pow(1 - t, 3);
        for (let i = 0; i < pos.length; i++) pos[i] = target[i] * (0.02 + 0.98 * k);
        geo.attributes.position.needsUpdate = true;
        if (t >= 1) { growing = false; geo.computeBoundingSphere(); }
      }
      if (!document.hidden) { controls.update(); renderer.render(scene, camera); }
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => {
      cancelAnimationFrame(raf); ro.disconnect(); controls.dispose();
      geo.dispose(); selGeo.dispose(); mat.dispose(); sprite.dispose(); renderer.dispose(); renderer.domElement.remove();
    };
  }, [points]);

  useEffect(() => { api.current?.paint(); }, [colors, dim]);
  useEffect(() => { api.current?.select(selected); }, [selected, points]);
  useEffect(() => { api.current?.spin(spin); }, [spin, points]);

  return <div ref={host} className="absolute inset-0" aria-label="Sessions in 3D: drag to turn, wheel to zoom, right-drag to pan" role="img" />;
}
