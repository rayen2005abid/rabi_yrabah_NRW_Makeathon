import {Routes,Route} from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './features/Dashboard'
import Production from './features/Production'
import Warehouse from './features/Warehouse'
import Inventory from './features/Inventory'
import BoxDetail from './features/BoxDetail'
import Robot from './features/Robot'
import DigitalTwin from './features/DigitalTwin'
import WhatIf from './features/WhatIf'
import Intake from './features/Intake'
import Faults from './features/Faults'
import Events from './features/Events'
import Analytics from './features/Analytics'
import Configuration from './features/Configuration'
import ProductionDetail from './features/ProductionDetail'
import DemoConsole from './features/DemoConsole'
import AdminPanel from './features/AdminPanel'
import FactoryConsole from './features/FactoryConsole'
import JuryShowcase from './features/JuryShowcase'

export default function App(){return <Routes><Route element={<Layout/>}>
  <Route path="/" element={<FactoryConsole/>}/><Route path="/dashboard" element={<Dashboard/>}/><Route path="/demo-showcase" element={<JuryShowcase/>}/>
  <Route path="/demo" element={<DemoConsole/>}/>
  <Route path="/production" element={<Production/>}/><Route path="/production/:id" element={<ProductionDetail/>}/>
  <Route path="/warehouse" element={<Warehouse/>}/><Route path="/inventory" element={<Inventory/>}/><Route path="/boxes/:id" element={<BoxDetail/>}/>
  <Route path="/robot" element={<Robot/>}/><Route path="/digital-twin" element={<DigitalTwin/>}/><Route path="/what-if" element={<WhatIf/>}/>
  <Route path="/intake" element={<Intake/>}/><Route path="/faults" element={<Faults/>}/><Route path="/events" element={<Events/>}/><Route path="/analytics" element={<Analytics/>}/><Route path="/configuration" element={<Configuration/>}/>
  <Route path="/admin" element={<AdminPanel/>}/>
</Route></Routes>}
