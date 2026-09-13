const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1'

export async function api<T=any>(path:string, options:RequestInit={}):Promise<T>{
  const res=await fetch(`${BASE}${path}`,{...options,headers:{'Content-Type':'application/json',...(options.headers||{})}})
  if(!res.ok){const body=await res.text();throw new Error(body||`${res.status}`)}
  return res.json()
}
export const get=<T=any>(path:string)=>api<T>(path)
export const post=<T=any>(path:string, body?:unknown)=>api<T>(path,{method:'POST',body:body===undefined?undefined:JSON.stringify(body)})
export const wsUrl=()=>`${BASE.replace(/^http/,'ws').replace('/api/v1','')}/api/v1/ws`
