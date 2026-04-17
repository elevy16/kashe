import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Navbar from '../components/Navbar';

function Home({ setIsAuthenticated }) {
  const [balance, setBalance] = useState(0);
  const navigate = useNavigate();

  useEffect(() => {
    const fetchBalance = async () => {
      const token = localStorage.getItem('token');
      const response = await fetch('http://127.0.0.1:5000/api/rewards', {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      const data = await response.json();
      setBalance(data.balance);
    };
    fetchBalance();
  }, []);

  const handleLogout = () => {
    localStorage.removeItem('token');
    setIsAuthenticated(false);
    navigate('/');
  };

  return (
    <div>
      <h1>Welcome to Kashé</h1>
      <p>Your points: {balance}</p>
      <button onClick={handleLogout}>Logout</button>
      <Navbar />
    </div>
  );
}

export default Home;