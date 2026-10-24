// A 3D model (glb / gltf) an agent made for an oracle, turned with the mouse. three.js and its glTF loader load only
// when a model is opened (the same lazy chunk family as the Map).
import { useEffect, useRef, useState } from "react";
import { AmbientLight, Box3, DirectionalLight, PerspectiveCamera, Scene, Vector3, WebGLRenderer } from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

export default function ModelView({ url, label }: { url: string; label: string }) {
  const host = useRef<HTMLDivElement>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    const el = host.current!;
    const renderer = new WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    el.appendChild(renderer.domElement);
    const scene = new Scene();
    scene.add(new AmbientLight(0xffffff, 1.4));
    const sun = new DirectionalLight(0xffffff, 2.2); sun.position.set(3, 5, 4); scene.add(sun);
    const camera = new PerspectiveCamera(45, 1, 0.01, 1000);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true; controls.autoRotate = !matchMedia("(prefers-reduced-motion: reduce)").matches; controls.autoRotateSpeed = 1;
    new GLTFLoader().load(url, g => {
      scene.add(g.scene);
      const box = new Box3().setFromObject(g.scene), size = box.getSize(new Vector3()).length() || 1, mid = box.getCenter(new Vector3());
      controls.target.copy(mid); camera.position.copy(mid).add(new Vector3(size * 0.6, size * 0.4, size * 0.9)); camera.near = size / 100; camera.far = size * 100; camera.updateProjectionMatrix();
    }, undefined, e => setErr(String((e as Error)?.message ?? e)));
    const size = () => { const w = el.clientWidth, h = el.clientHeight; renderer.setSize(w, h, false); renderer.domElement.style.width = "100%"; renderer.domElement.style.height = "100%"; camera.aspect = w / Math.max(h, 1); camera.updateProjectionMatrix(); };
    const ro = new ResizeObserver(size); ro.observe(el); size();
    let raf = 0;
    const tick = () => { if (!document.hidden) { controls.update(); renderer.render(scene, camera); } raf = requestAnimationFrame(tick); };
    tick();
    return () => { cancelAnimationFrame(raf); ro.disconnect(); controls.dispose(); renderer.dispose(); renderer.domElement.remove(); };
  }, [url]);
  return (
    <div className="relative h-full w-full" role="img" aria-label={label}>
      <div ref={host} className="absolute inset-0" />
      {err && <p className="absolute inset-x-0 bottom-0 m-0 bg-panel p-3 text-xs text-danger">This model did not load: {err}</p>}
    </div>
  );
}
