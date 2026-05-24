import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom' // <--- NEW IMPORTS

import App from './App.jsx' // Your Admin Dashboard
import PublicBracket from './PublicBracket.jsx' // The new page we just made!
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        {/* URL: http://localhost:5173/ */}
        <Route path="/" element={<App />} />
        
        {/* URL: http://localhost:5173/public/YOUR_TOURNAMENT_ID */}
        <Route path="/public/:tournamentId" element={<PublicBracket />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
)