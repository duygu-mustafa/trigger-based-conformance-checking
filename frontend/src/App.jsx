import { useState, useEffect } from 'react'
import './App.css'
import Timeline from './components/Timeline'
import case35616431 from './data/case_35616431.json'
import case30031915 from './data/case_30031915.json'

const CASE_MAP = {
  '35616431': case35616431,
  '30031915': case30031915
}

function App() {
  const [caseId, setCaseId] = useState('35616431')
  const [caseData, setCaseData] = useState(null)

  useEffect(() => {
    setCaseData(CASE_MAP[caseId])
  }, [caseId])

  if (!caseData) return <div>Loading...</div>

  return (
    <div className="app-container">
      <header className="app-header">
        <h1>SBT Conformance Visualization</h1>
        <div className="case-selector">
          <label htmlFor="case-select">Select Case: </label>
          <select 
            id="case-select" 
            value={caseId} 
            onChange={(e) => setCaseId(e.target.value)}
          >
            {Object.keys(CASE_MAP).map(id => (
              <option key={id} value={id}>{id}</option>
            ))}
          </select>
        </div>
      </header>
      
      <main className="visualization-area">
        <Timeline data={caseData} />
      </main>
    </div>
  )
}

export default App
