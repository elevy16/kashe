import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import confetti from 'canvas-confetti';
import Navbar from '../components/Navbar';
import './ChallengeDetail.css';

function ChallengeDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [challenge, setChallenge] = useState(null);
  const [enrollment, setEnrollment] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [successMessage, setSuccessMessage] = useState('');

  const formatDate = (value) => {
    if (!value) return 'No deadline';
    const date = new Date(value);
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });
  };

  const fetchChallenge = async () => {
    try {
      setLoading(true);
      setError(null);
      setSuccessMessage('');
      const token = localStorage.getItem('token');

      const [challengeResponse, enrollmentsResponse] = await Promise.all([
        fetch(`http://127.0.0.1:5000/api/challenges/${id}`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetch('http://127.0.0.1:5000/api/enrollments', {
          headers: { Authorization: `Bearer ${token}` },
        }),
      ]);

      if (!challengeResponse.ok) {
        const errData = await challengeResponse.json();
        throw new Error(errData.error || 'Challenge not found');
      }

      const challengeData = await challengeResponse.json();
      const enrollmentsData = await enrollmentsResponse.json();
      const matchedEnrollment = enrollmentsData.find(
        (item) => String(item.challenge_id) === String(id)
      );

      setChallenge(challengeData);
      setEnrollment(matchedEnrollment || null);
    } catch (err) {
      setError(err.message || 'Unable to load challenge details');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchChallenge();
  }, [id]);

  const handleJoin = async () => {
    try {
      setActionLoading(true);
      const token = localStorage.getItem('token');

      const response = await fetch('http://127.0.0.1:5000/api/enroll', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ challenge_id: Number(id) }),
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.error || 'Failed to join challenge');
      }

      await fetchChallenge();
    } catch (err) {
      setError(err.message || 'Failed to join challenge');
    } finally {
      setActionLoading(false);
    }
  };

  const handleLogClass = async () => {
    if (!enrollment) return;
    try {
      setActionLoading(true);
      const token = localStorage.getItem('token');

      const response = await fetch('http://127.0.0.1:5000/api/checkin', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ enrollment_id: enrollment.id }),
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.error || 'Failed to log class');
      }

      const result = await response.json();
      if (result.completed) {
        confetti({
          particleCount: 150,
          spread: 80,
          origin: { y: 0.6 },
          colors: ['#8BAF9F', '#F7F5F2', '#2D2D2D', '#E8E0D8'],
        });
        setSuccessMessage(`Challenge Complete! 🎉 You earned ${result.points_earned} points!`);
      }

      await fetchChallenge();
    } catch (err) {
      setError(err.message || 'Failed to log class');
    } finally {
      setActionLoading(false);
    }
  };

  const enrolled = !!enrollment;
  const completed = enrolled && enrollment.classes_completed >= enrollment.required_classes;
  const progressPercent = completed
    ? 100
    : enrolled
    ? Math.min((enrollment.classes_completed / enrollment.required_classes) * 100, 100)
    : 0;

  return (
    <div className="challenge-detail-container">
      <div className="challenge-detail-content">
        <button className="back-button" onClick={() => navigate('/challenges')}>
          ← Back
        </button>

        {loading ? (
          <p className="loading-message">Loading challenge...</p>
        ) : error ? (
          <p className="error-message">{error}</p>
        ) : challenge ? (
          <div className="detail-card">
            <h1 className="detail-title">{challenge.title}</h1>
            <div className="points-badge">🏆 {challenge.points_reward} pts</div>
            <p className="detail-meta">Complete {challenge.required_classes} classes</p>
            <p className="detail-meta">{challenge.deadline ? formatDate(challenge.deadline) : 'No deadline'}</p>

            {completed && <div className="completed-badge">Completed! 🎉</div>}

            {enrolled && (
              <div className="progress-section">
                <div className="progress-label">{enrollment.classes_completed} / {enrollment.required_classes} classes completed</div>
                <div className="progress-bar">
                  <div className="progress-fill" style={{ width: `${progressPercent}%` }} />
                </div>
              </div>
            )}

            {successMessage && <div className="success-box">{successMessage}</div>}

            {!enrolled ? (
              <button className="action-button" onClick={handleJoin} disabled={actionLoading}>
                Join Challenge
              </button>
            ) : !completed ? (
              <button className="action-button" onClick={handleLogClass} disabled={actionLoading}>
                {actionLoading ? 'Logging...' : 'Log a Class'}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      <Navbar />
    </div>
  );
}

export default ChallengeDetail;
