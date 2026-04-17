import { Link, useLocation } from 'react-router-dom';

function Navbar() {
  const location = useLocation();
  return (
    <nav>
      <Link to="/home" className={location.pathname === '/home' ? 'active' : ''}>Home</Link>
      <Link to="/challenges" className={location.pathname === '/challenges' ? 'active' : ''}>Challenges</Link>
      <Link to="/rewards" className={location.pathname === '/rewards' ? 'active' : ''}>Rewards</Link>
      <Link to="/chat" className={location.pathname === '/chat' ? 'active' : ''}>Chat</Link>
    </nav>
  );
}

export default Navbar;