/** @type {import('next').NextConfig} */
const nextConfig = {
  // 백엔드(FastAPI)로 프록시. 브라우저는 같은 출처로만 호출해 CORS 설정을 피한다.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination:
          (process.env.PMS_BACKEND_ORIGIN ?? "http://localhost:8000") + "/api/:path*",
      },
    ];
  },
};

export default nextConfig;
