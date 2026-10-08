// 把站点内的相对路径拼成带 baseURL 的完整地址
// 站点挂在仓库子路径下, 直接写 /resource/... 会丢前缀, 所以统一走这里
export function useAssetUrl() {
  const base = useRuntimeConfig().app.baseURL || '/'
  return (path: string) => {
    const clean = String(path).replace(/^\/+/, '')
    // 视频文件名含中文, 交给 encodeURI 转义, 否则部分浏览器会请求失败
    return encodeURI(`${base}${clean}`)
  }
}
