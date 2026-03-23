// Inline script to prevent FOUC — sets dark class before first paint
export const themeScript = `(function(){var t=localStorage.getItem('theme');if(t==='dark'||(t==null&&matchMedia('(prefers-color-scheme:dark)').matches))document.documentElement.classList.add('dark')})()`;
