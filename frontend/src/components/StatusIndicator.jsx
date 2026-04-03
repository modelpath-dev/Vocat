const STATUS_CONFIG = {
  disconnected: { color: 'bg-gray-500', label: 'Not Connected', pulse: false },
  connecting: { color: 'bg-yellow-500', label: 'Connecting...', pulse: true },
  connected: { color: 'bg-green-500', label: 'Connected - Listening...', pulse: false },
  speaking: { color: 'bg-indigo-500', label: 'AI Speaking...', pulse: true },
  error: { color: 'bg-red-500', label: 'Error', pulse: true },
};

export default function StatusIndicator({ status }) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.disconnected;

  return (
    <div className="flex items-center gap-3 bg-gray-800/50 backdrop-blur-sm px-5 py-3 rounded-xl border border-gray-700/50">
      <span
        className={`h-3 w-3 rounded-full ${config.color} ${config.pulse ? 'animate-pulse' : ''}`}
      />
      <span className="text-sm font-medium text-gray-300">{config.label}</span>
    </div>
  );
}
