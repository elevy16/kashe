import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';

function Navbar({ setIsAuthenticated }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [balance, setBalance] = useState(null);
  const [toastMessage, setToastMessage] = useState(null);
  const [toastVisible, setToastVisible] = useState(false);
  const prevBalanceRef = useRef(null);

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) return undefined;

    const pollRewards = async () => {
      try {
        const res = await fetch('http://127.0.0.1:5000/api/rewards', {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) return;
        const data = await res.json();
        if (typeof data.balance === 'undefined') return;

        const newBal = data.balance;
        const prev = prevBalanceRef.current;
        if (prev !== null && typeof newBal === 'number' && newBal > prev) {
          const delta = newBal - prev;
          setToastVisible(false);
          setToastMessage(`🎉 Challenge complete! +${delta} pts`);
        }
        prevBalanceRef.current = newBal;
        setBalance(newBal);
      } catch {
        // ignore
      }
    };

    pollRewards();
    const id = window.setInterval(pollRewards, 5000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (!toastMessage) return undefined;

    setToastVisible(false);
    let raf1 = 0;
    let raf2 = 0;
    const hideTimer = setTimeout(() => setToastVisible(false), 2000);
    const removeTimer = setTimeout(() => {
      setToastMessage(null);
      setToastVisible(false);
    }, 2300);

    raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => setToastVisible(true));
    });

    return () => {
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(raf2);
      clearTimeout(hideTimer);
      clearTimeout(removeTimer);
    };
  }, [toastMessage]);

  const handleLogout = () => {
    try {
      sessionStorage.removeItem('kashe_chat_history');
      sessionStorage.removeItem('kashe_pending_log_challenge');
    } catch {
      // ignore
    }
    localStorage.clear();
    setIsAuthenticated?.(false);
    navigate('/');
  };

  const navItems = [
    { path: '/home', label: 'Home' },
    { path: '/challenges', label: 'Challenges' },
    { path: '/rewards', label: 'Rewards' },
    { path: '/profile', label: 'Profile' },
    { path: '/chat', label: 'Chat' },
  ];

  return (
    <>
      {toastMessage != null && (
        <div
          className={`socket-toast ${toastVisible ? 'socket-toast--visible' : ''}`}
          role="status"
          aria-live="polite"
        >
          {toastMessage}
        </div>
      )}

      <aside className="sidebar-nav">
        <div className="sidebar-content">
          <div className="sidebar-top">
            <div className="sidebar-brand-block">
              <div className="sidebar-brand">
                <span className="sidebar-logo" aria-hidden>
                  {'\u25C6'}
                </span>
                <span className="sidebar-brand-name">kashé</span>
              </div>
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

            <button type="button" className="sidebar-logout" onClick={handleLogout}>
              Logout
            </button>
          </div>
        </div>
      </aside>

      <nav className="bottom-nav">
        {navItems.filter((item) => item.path !== '/chat').map((item) => (
          <Link key={item.path} to={item.path} className={location.pathname === item.path ? 'active' : ''}>
            {item.label}
          </Link>
        ))}
      </nav>
    </>
  );
}

export default Navbar;
