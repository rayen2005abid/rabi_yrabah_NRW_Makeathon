import {useEffect} from 'react'
import {useQueryClient} from '@tanstack/react-query'
import {wsUrl} from '../api/client'
export function useWarehouseRealtime(){
  const qc=useQueryClient()
  useEffect(()=>{
    let ws:WebSocket|undefined; let timer:number|undefined; let closed=false
    const connect=()=>{
      if(closed)return
      ws=new WebSocket(wsUrl())
      ws.onmessage=()=>{qc.invalidateQueries()}
      ws.onclose=()=>{if(!closed)timer=window.setTimeout(connect,1500)}
    }
    connect();return()=>{closed=true;if(timer)clearTimeout(timer);ws?.close()}
  },[qc])
}
