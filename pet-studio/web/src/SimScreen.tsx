import { useEffect, useRef } from "react";
import { CANVAS_H, CANVAS_W } from "./sim";
import { gifFor, simCanvas, tap, useSim } from "./simstore";

/** The simulated pet screen (320x480 drawn at 240x360). Frame mode plays the pack's GIF with the
 * caption; canvas mode shows what the app drew. A click is a tap, in pet coordinates. */
export function SimScreen() {
  const view = useSim();
  const cv = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const src = simCanvas();
    if (view?.canvas && src && cv.current) cv.current.getContext("2d")!.drawImage(src, 0, 0);
  }, [view?.frame, view?.canvas]);
  return (
    <>
      <div className="screen" onClick={(e) => {
        const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
        tap(Math.round((e.clientX - r.left) * 320 / r.width), Math.round((e.clientY - r.top) * 480 / r.height));
      }}>
        {view ? <>
          {view.canvas
            ? <canvas ref={cv} className="petcanvas" width={CANVAS_W} height={CANVAS_H} />
            : <><img className="petgif" src={gifFor(view)} /><div className="caption">{view.caption}</div></>}
          <div className="hud">{view.status}</div>
          <span className="mode">{view.canvas ? "canvas" : "frame"}</span>
        </> : <div className="dim center">compile, then ▶ Simulate<br />click the screen to tap</div>}
      </div>
      {view && <pre className="simlog">{view.log.join("\n")}</pre>}
    </>
  );
}
