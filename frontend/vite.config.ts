import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({plugins:[react()],server:{proxy:{'/api':'http://127.0.0.1:8765'}},build:{rollupOptions:{output:{manualChunks:{react:['react','react-dom'],'math':['katex','rehype-katex','remark-math'],motion:['gsap','@gsap/react'],markdown:['react-markdown']}}}}});
