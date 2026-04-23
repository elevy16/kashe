import { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';

function Navbar({ setIsAuthenticated }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [balance, setBalance] = useState(null);

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) return;

    fetch('http://127.0.0.1:5000/api/rewards', {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => res.json())
      .then((data) => {
        if (data && typeof data.balance !== 'undefined') {
          setBalance(data.balance);
        }
      })
      .catch(() => {});
  }, []);

  const handleLogout = () => {
    localStorage.clear();
    setIsAuthenticated(false);
    navigate('/');
  };

  const navItems = [
    { path: '/home', label: 'Home' },
    { path: '/challenges', label: 'Challenges' },
    { path: '/rewards', label: 'Rewards' },
    { path: '/chat', label: 'Chat' },
  ];

  return (
    <>
      <aside className="sidebar-nav">
        <div className="sidebar-content">
          <div className="sidebar-top">
            <div className="sidebar-brand">
              <span className="sidebar-logo">◇</span>
              <span>kashé</span>
            </div>

            <div className="sidebar-links">
              {navItems.map((item) => (
                <Link
                  key={item.path}
                  to={item.path}
                  className={`sidebar-link ${location.pathname === item.path ? 'active' : ''}`}
                >
                  {item.label}
                </Link>
              ))}
            </div>
          </div>

          <div className="sidebar-bottom">
            <div className="sidebar-balance">
              <p className="balance-value">{balance !== null ? `${balance} pts` : '-- pts'}</p>
              <p className="balance-label">your balance</p>
            </div>

            <button className="sidebar-logout" onClick={handleLogout}>
              Logout
            </button>
          </div>
        </div>
      </aside>

      <nav className="bottom-nav">
        {navItems.map((item) => (
          <Link key={item.path} to={item.path} className={location.pathname === item.path ? 'active' : ''}>
            {item.label}
          </Link>
        ))}
      </nav>
    </>
  );
}

export default Navbar;