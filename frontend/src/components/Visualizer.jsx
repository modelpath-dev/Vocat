import { useEffect, useRef } from 'react';

export default function Visualizer({ isActive }) {
  const canvasRef = useRef(null);
  const animRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;

    const bars = 48;
    const barWidth = w / bars - 2;

    function draw() {
      ctx.clearRect(0, 0, w, h);

      for (let i = 0; i < bars; i++) {
        const amplitude = isActive
          ? Math.random() * 0.6 + 0.1
          : 0.03 + Math.sin(Date.now() / 1000 + i * 0.3) * 0.02;

        const barHeight = amplitude * h;
        const x = i * (barWidth + 2);
        const y = (h - barHeight) / 2;

        const gradient = ctx.createLinearGradient(x, y, x, y + barHeight);
        if (isActive) {
          gradient.addColorStop(0, 'rgba(129, 140, 248, 0.8)');
          gradient.addColorStop(1, 'rgba(99, 102, 241, 0.4)');
        } else {
          gradient.addColorStop(0, 'rgba(75, 85, 99, 0.4)');
          gradient.addColorStop(1, 'rgba(55, 65, 81, 0.2)');
        }

        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.roundRect(x, y, barWidth, barHeight, 2);
        ctx.fill();
      }

      animRef.current = requestAnimationFrame(draw);
    }

    draw();
    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current);
    };
  }, [isActive]);

  return (
    <canvas
      ref={canvasRef}
      width={400}
      height={80}
      className="w-full h-20 rounded-lg"
    />
  );
}
