export default function CallButton({ isActive, onStart, onStop }) {
  if (isActive) {
    return (
      <button
        onClick={onStop}
        className="group relative w-20 h-20 rounded-full bg-red-600 hover:bg-red-500 text-white shadow-lg shadow-red-600/30 hover:shadow-red-500/40 transition-all duration-200 cursor-pointer"
      >
        <svg className="w-7 h-7 mx-auto" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
        <span className="absolute -bottom-7 left-1/2 -translate-x-1/2 text-xs text-gray-400 font-medium whitespace-nowrap">
          End Call
        </span>
      </button>
    );
  }

  return (
    <button
      onClick={onStart}
      className="group relative w-20 h-20 rounded-full bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-600/30 hover:shadow-indigo-500/40 transition-all duration-200 cursor-pointer"
    >
      <svg className="w-7 h-7 mx-auto" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 6.75c0 8.284 6.716 15 15 15h2.25a2.25 2.25 0 002.25-2.25v-1.372c0-.516-.351-.966-.852-1.091l-4.423-1.106c-.44-.11-.902.055-1.173.417l-.97 1.293c-.282.376-.769.542-1.21.38a12.035 12.035 0 01-7.143-7.143c-.162-.441.004-.928.38-1.21l1.293-.97c.363-.271.527-.734.417-1.173L6.963 3.102a1.125 1.125 0 00-1.091-.852H4.5A2.25 2.25 0 002.25 4.5v2.25z" />
      </svg>
      <span className="absolute -bottom-7 left-1/2 -translate-x-1/2 text-xs text-gray-400 font-medium whitespace-nowrap">
        Start Call
      </span>
    </button>
  );
}
