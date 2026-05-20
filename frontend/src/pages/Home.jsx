import { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import Navbar from '../components/Navbar';
import './Home.css';

function Home({ setIsAuthenticated }) {
  const [balance, setBalance] = useState(0);
  const [enrollments, setEnrollments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const token = localStorage.getItem('token');

      // Fetch balance
      const rewardsResponse = await fetch('http://127.0.0.1:5000/api/rewards', {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      const rewardsData = await rewardsResponse.json();
      setBalance(rewardsData.balance || 0);

      // Fetch enrolled challenges
      const enrollmentsResponse = await fetch('http://127.0.0.1:5000/api/enrollments', {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      if (!enrollmentsResponse.ok) {
        throw new Error('Failed to fetch enrollments');
      }
      const enrollmentsData = await enrollmentsResponse.json();
      setEnrollments(enrollmentsData || []);
    } catch (err) {
      setError(err.message || 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  return (
    <div className="home-container">
      <div className="home-content">
        <h1 className="logo logo-mobile">◇ kashé</h1>

        <h2 className="balance-display">{balance}</h2>
        <p className="balance-label">points</p>

        {loading && <p className="loading-message">Loading...</p>}

        {error && <p className="error-message">{error}</p>}

        <div className="challenges-section">
          <h3 className="section-title">my challenges</h3>

          {!loading && enrollments.length === 0 && (
            <div className="home-empty-state">
              <span className="home-empty-diamond" aria-hidden>
                {'\u25C6'}
              </span>
              <p className="home-empty-title">No challenges yet</p>
              <p className="home-empty-sub">Join a challenge to start earning points</p>
              <Link to="/challenges" className="browse-challenges-button home-empty-browse">
                Browse Challenges →
              </Link>
            </div>
          )}

          <div className="enrollments-grid">
            {enrollments.map((enrollment) => {
              const isComplete =
                enrollment.required_classes > 0 &&
                enrollment.classes_completed >= enrollment.required_classes;
              const progress = isComplete
                ? 100
                : enrollment.required_classes > 0
                  ? (enrollment.classes_completed / enrollment.required_classes) * 100
                  : 0;
              return (
                <div
                  key={enrollment.id}
                  className={`enrollment-card${isComplete ? ' enrollment-card--completed' : ''}`}
                  onClick={() => navigate(`/challenges/${enrollment.challenge_id}`)}
                >
                  {isComplete && (
                    <span className="enrollment-badge" aria-label="Challenge completed">
                      ✓ Completed
                    </span>
                  )}
                  <h4 className={`enrollment-title${isComplete ? ' enrollment-title--done' : ''}`}>
                    {enrollment.title}
                  </h4>
                  <div className="progress-container">
                    <div className="progress-bar">
                      <div
                        className={`progress-fill${isComplete ? ' progress-fill--complete' : ''}`}
                        style={{ width: `${progress}%` }}
                      />
                    </div>
                    <p className="progress-text">
                      {enrollment.classes_completed} / {enrollment.required_classes} classes
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
          {!loading && enrollments.length > 0 && (
            <button type="button" className="browse-challenges-button" onClick={() => navigate('/challenges')}>
              Browse Challenges →
            </button>
          )}
        </div>

      </div>

      <Navbar setIsAuthenticated={setIsAuthenticated} />
    </div>
  );
}

export default Home;