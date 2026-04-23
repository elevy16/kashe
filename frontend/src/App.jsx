import { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import Login from './pages/Login';
import Register from './pages/Register';
import Home from './pages/Home';
import Challenges from './pages/Challenges';
import Rewards from './pages/Rewards';
import Chat from './pages/Chat';
import Profile from './pages/Profile';

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(!!localStorage.getItem('token'));

  useEffect(() => {
    const checkAuth = () => {
      setIsAuthenticated(!!localStorage.getItem('token'));
    };

    // Check on mount
    checkAuth();

    // Listen for storage changes (e.g., from other tabs)
    window.addEventListener('storage', checkAuth);

    return () => window.removeEventListener('storage', checkAuth);
  }, []);

  return (
    <Router>
      <Routes>
        <Route path="/" element={<Login setIsAuthenticated={setIsAuthenticated} />} />
        <Route path="/register" element={<Register />} />
        <Route path="/home" element={isAuthenticated ? <Home setIsAuthenticated={setIsAuthenticated} /> : <Navigate to="/" />} />
        <Route path="/challenges" element={isAuthenticated ? <Challenges /> : <Navigate to="/" />} />
        <Route path="/rewards" element={isAuthenticated ? <Rewards /> : <Navigate to="/" />} />
        <Route path="/chat" element={isAuthenticated ? <Chat /> : <Navigate to="/" />} />
        <Route path="/profile" element={isAuthenticated ? <Profile /> : <Navigate to="/" />} />
      </Routes>
    </Router>
  );
}

export default App;
