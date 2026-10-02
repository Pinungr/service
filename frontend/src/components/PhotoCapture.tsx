import { useEffect, useRef, useState } from 'react';
import { ErrorBox, Modal } from './ui';

/**
 * Capture a photo with the browser camera, or upload one. Only the image bytes leave
 * this component; the backend validates, normalises and stores them.
 */
export function PhotoCapture({ title, onPhoto, onClose, busy = false, error }: {
  title: string; onPhoto: (photo: Blob, filename: string) => void; onClose: () => void; busy?: boolean; error?: unknown;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const [cameraError, setCameraError] = useState('');
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraError('This browser cannot use the camera here. Upload a photo instead.');
      return;
    }
    navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false })
      .then((media) => {
        if (cancelled) { media.getTracks().forEach((t) => t.stop()); return; }
        stream.current = media;
        if (video.current) { video.current.srcObject = media; video.current.play().catch(() => undefined); }
        setReady(true);
      })
      .catch(() => setCameraError('No camera is available or permission was refused. Upload a photo instead.'));
    return () => { cancelled = true; stream.current?.getTracks().forEach((t) => t.stop()); };
  }, []);

  const capture = () => {
    const v = video.current;
    if (!v || !v.videoWidth) return;
    const canvas = document.createElement('canvas');
    canvas.width = v.videoWidth;
    canvas.height = v.videoHeight;
    canvas.getContext('2d')?.drawImage(v, 0, 0);
    canvas.toBlob((blob) => { if (blob) onPhoto(blob, 'capture.jpg'); }, 'image/jpeg', 0.92);
  };

  return (
    <Modal title={title} onClose={onClose} footer={<>
      <label className="button" style={{ display: 'inline-flex', alignItems: 'center' }}>
        Upload photo
        <input type="file" accept="image/jpeg,image/png,image/webp" hidden
               onChange={(e) => { const file = e.target.files?.[0]; if (file) onPhoto(file, file.name); }} />
      </label>
      <button className="primary" onClick={capture} disabled={!ready || busy}>{busy ? 'Saving…' : 'Capture photo'}</button>
      <button onClick={onClose}>Cancel</button>
    </>}>
      {cameraError ? <div className="notice">{cameraError}</div> : <video ref={video} className="camera" muted playsInline />}
      <ErrorBox error={error} />
    </Modal>
  );
}

export function photoForm(photo: Blob, filename: string, extra: Record<string, string | number | null | undefined> = {}) {
  const form = new FormData();
  form.append('file', photo, filename);
  for (const [key, value] of Object.entries(extra)) if (value !== null && value !== undefined) form.append(key, String(value));
  return form;
}
