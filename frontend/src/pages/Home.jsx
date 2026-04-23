import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Navbar from '../components/Navbar';
import './Home.css';

function Home({ setIsAuthenticated }) {
  const [balance, setBalance] = useState(0);
  const [enrollments, setEnrollments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [loggingId, setLoggingId] = useState(null);
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

  const handleLogClass = async (enrollmentId, enrollmentIndex) => {
    try {
      setLoggingId(enrollmentId);
      const token = localStorage.getItem('token');

      const response = await fetch('http://127.0.0.1:5000/api/checkin', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ enrollment_id: enrollmentId }),
      });

      if (!response.ok) {
        throw new Error('Failed to log class');
      }

      const data = await response.json();

      // Update the enrollment with new progress
      setEnrollments((prev) => {
        const updated = [...prev];
        updated[enrollmentIndex] = {
          ...updated[enrollmentIndex],
          classes_completed: data.classes_completed,
        };
        return updated;
      });

      // Update balance if challenge was completed
      if (data.points_earned > 0) {
        setBalance((prev) => prev + data.points_earned);
      }
    } catch (err) {
      setError(err.message || 'An error occurred while logging class');
    } finally {
      setLoggingId(null);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    setIsAuthenticated(false);
    navigate('/');
  };

  return (
    <div className="home-container">
      <div className="home-content">
        <h1 className="logo">◇ kashé</h1>

        <h2 className="balance-display">{balance}</h2>
        <p className="balance-label">points</p>

        {loading && <p className="loading-message">Loading...</p>}

        {error && <p className="error-message">{error}</p>}

        <div className="challenges-section">
          <h3 className="section-title">my challenges</h3>

          {!loading && enrollments.length === 0 && (
            <p className="no-enrollments">No active challenges. Explore new challenges!</p>
          )}

          <div className="enrollments-grid">
            {enrollments.map((enrollment, index) => {
              const progress = enrollment.required_classes > 0
                ? (enrollment.classes_completed / enrollment.required_classes) * 100
                : 0;
              const isComplete =
                enrollment.classes_completed >= enrollment.required_classes;

              return (
                <div key={enrollment.id} className="enrollment-card">
                  <h4 className="enrollment-title">{enrollment.title}</h4>
                  <div className="progress-container">
                    <div className="progress-bar">
                      <div
                        className="progress-fill"
                        style={{ width: `${progress}%` }}
                      ></div>
                    </div>
                    <p className="progress-text">
                      {enrollment.classes_completed} / {enrollment.required_classes} classes
                    </p>
                  </div>
                  <button
                    className={`log-class-button ${isComplete ? 'complete' : ''}`}
                    onClick={() => handleLogClass(enrollment.id, index)}
                    disabled={isComplete || loggingId === enrollment.id}
                  >
                    {isComplete ? 'Completed' : 'Log a Class'}
                  </button>
                </div>
              );
            })}
          </div>
        </div>

        <button className="logout-button" onClick={handleLogout}>
          Logout
        </button>
      </div>

      <Navbar />
    </div>
  );
}

export default Home;