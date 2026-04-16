/** Базовый URL REST API: в production работает через same-origin proxy `/api`. */
export const API_BASE = import.meta.env.VITE_API_BASE ?? '/api'
