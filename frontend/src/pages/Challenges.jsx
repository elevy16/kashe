import { useState, useEffect } from 'react';
import Navbar from '../components/Navbar';
import './Challenges.css';

function Challenges() {
  const [challenges, setChallenges] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [enrolledChallenges, setEnrolledChallenges] = useState(new Set());
  const [enrollingId, setEnrollingId] = useState(null);

  useEffect(() => {
    const fetchChallenges = async () => {
      try {
        setLoading(true);
        setError(null);
        const token = localStorage.getItem('token');
        
        const challengesResponse = await fetch('http://127.0.0.1:5000/api/challenges', {
          headers: {
            'Authorization': `Bearer ${token}`,
          },
        });

        if (!challengesResponse.ok) {
          throw new Error('Failed to fetch challenges');
        }

        const challengesData = await challengesResponse.json();
        setChallenges(challengesData || []);

        // Fetch enrollments to pre-populate enrolled state
        const enrollmentsResponse = await fetch('http://127.0.0.1:5000/api/enrollments', {
          headers: {
            'Authorization': `Bearer ${token}`,
          },
        });

        if (enrollmentsResponse.ok) {
          const enrollmentsData = await enrollmentsResponse.json();
          const enrolledIds = new Set(enrollmentsData.map((enrollment) => enrollment.challenge_id));
          setEnrolledChallenges(enrolledIds);
        }
      } catch (err) {
        setError(err.message || 'An error occurred while fetching challenges');
      } finally {
        setLoading(false);
      }
    };

    fetchChallenges();
  }, []);

  const handleEnroll = async (challengeId) => {
    try {
      setEnrollingId(challengeId);
      const token = localStorage.getItem('token');

      const response = await fetch('http://127.0.0.1:5000/api/enroll', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ challenge_id: challengeId }),
      });

      if (response.status === 409) {
        // Already enrolled
        setEnrolledChallenges((prev) => new Set(prev).add(challengeId));
        return;
      }

      if (!response.ok) {
        throw new Error('Failed to enroll in challenge');
      }

      setEnrolledChallenges((prev) => new Set(prev).add(challengeId));
    } catch (err) {
      setError(err.message || 'An error occurred during enrollment');
    } finally {
      setEnrollingId(null);
    }
  };

  return (
    <div className="challenges-container">
      <div className="challenges-content">
        <h1>Challenges</h1>

        {loading && <p className="loading-message">Loading challenges...</p>}

        {error && <p className="error-message">{error}</p>}

        {!loading && !error && challenges.length === 0 && (
          <p className="no-challenges">No challenges available</p>
        )}

        <div className="challenges-grid">
          {challenges.map((challenge) => (
            <div key={challenge.id} className="challenge-card">
              <h2 className="challenge-title">{challenge.title}</h2>
              <p className="challenge-subtitle">
                {challenge.required_classes} classes · {challenge.points_reward} pts
              </p>
              <button
                className={`enroll-button ${
                  enrolledChallenges.has(challenge.id) ? 'enrolled' : ''
                }`}
                onClick={() => handleEnroll(challenge.id)}
                disabled={enrolledChallenges.has(challenge.id) || enrollingId === challenge.id}
              >
                {enrolledChallenges.has(challenge.id) ? 'Enrolled' : 'Join'}
              </button>
            </div>
          ))}
        </div>
      </div>

      <Navbar />
    </div>
  );
}

export default Challenges;