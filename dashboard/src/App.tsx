import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Overview from './pages/Overview'
import Topology from './pages/Topology'
import ChaosLab from './pages/ChaosLab'
import FaultLibrary from './pages/FaultLibrary'
import Agent from './pages/Agent'
import Incidents from './pages/Incidents'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/overview" replace />} />
          <Route path="overview" element={<Overview />} />
          <Route path="topology" element={<Topology />} />
          <Route path="incidents" element={<Incidents />} />
          <Route path="chaos" element={<ChaosLab />} />
          <Route path="faultlib" element={<FaultLibrary />} />
          <Route path="agent" element={<Agent />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
