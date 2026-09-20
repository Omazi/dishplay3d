'use client';
import { useEffect, useRef, useState, type RefObject } from 'react';
import { imageDifference, inspectPixels, type ImageQuality } from '@/lib/capture-quality';

export function useCaptureFeedback(camera: RefObject<HTMLVideoElement | null>, live: boolean) {
  const [feedback, setFeedback] = useState<{
    quality: ImageQuality;
    moving: boolean;
    similar: boolean;
    ready: boolean;
    tick: number;
  } | null>(null);
  const pixels = useRef<Uint8Array | null>(null);
  const saved = useRef<Uint8Array | null>(null);
  useEffect(() => {
    setFeedback(null);
    pixels.current = null;
    saved.current = null;
    if (!live) return;
    const canvas = document.createElement('canvas');
    canvas.width = 160;
    canvas.height = 120;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) return;
    let previous: Uint8Array | null = null,
      stable = 0;
    const timer = window.setInterval(() => {
      const video = camera.current;
      if (document.hidden || !video?.videoWidth || video.readyState < 2) return;
      try {
        ctx.drawImage(video, 0, 0, 160, 120);
        const { quality, gray } = inspectPixels(ctx.getImageData(0, 0, 160, 120).data, 160, 120);
        const difference = imageDifference(gray, previous);
        const moving = difference === null || difference > 5;
        stable = moving ? 0 : stable + 1;
        const fromSaved = imageDifference(gray, saved.current);
        const similar = fromSaved !== null && fromSaved < 7;
        pixels.current = gray;
        previous = gray;
        setFeedback({
          quality,
          moving,
          similar,
          ready: stable >= 2 && !similar && !quality.warnings.length,
          tick: Date.now(),
        });
      } catch {
        setFeedback(null);
      }
    }, 500);
    return () => {
      clearInterval(timer);
      canvas.width = 0;
      canvas.height = 0;
    };
  }, [camera, live]);
  return {
    feedback,
    markCaptured: (gray?: Uint8Array) => {
      saved.current = gray ?? pixels.current;
    },
  };
}
