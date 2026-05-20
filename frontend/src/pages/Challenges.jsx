import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import Navbar from '../components/Navbar';
import './Challenges.css';

function Challenges() {
  const navigate = useNavigate();
  const [challenges, setChallenges] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [enrollmentsByChallengeId, setEnrollmentsByChallengeId] = useState({});
  const [enrollingId, setEnrollingId] = useState(null);
  /** Local only — cleared when leaving this page (no URL/storage persistence). */
  const [searchQuery, setSearchQuery] = useState('');

  const loadChallengesAndEnrollments = useCallback(async () => {
    const token = localStorage.getItem('token');

    const challengesResponse = await fetch('http://127.0.0.1:5000/api/challenges', {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (!challengesResponse.ok) {
      throw new Error('Failed to fetch challenges');
    }

    const challengesData = await challengesResponse.json();
    setChallenges(challengesData || []);

    const enrollmentsResponse = await fetch('http://127.0.0.1:5000/api/enrollments', {
      headers: { Authorization: `Bearer ${token}` },
    });

    const map = {};
    if (enrollmentsResponse.ok) {
      const enrollmentsData = await enrollmentsResponse.json();
      (enrollmentsData || []).forEach((row) => {
        map[row.challenge_id] = row;
      });
    }
    setEnrollmentsByChallengeId(map);
  }, []);

  useEffect(() => {
    const run = async () => {
      try {
        setLoading(true);
        setError(null);
        await loadChallengesAndEnrollments();
      } catch (err) {
        setError(err.message || 'An error occurred while fetching challenges');
      } finally {
        setLoading(false);
      }
    };
    run();
  }, [loadChallengesAndEnrollments]);

  const handleEnroll = async (challengeId) => {
    try {
      setEnrollingId(challengeId);
      const token = localStorage.getItem('token');

      const response = await fetch('http://127.0.0.1:5000/api/enroll', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ challenge_id: challengeId }),
      });

      if (response.status === 409) {
        await loadChallengesAndEnrollments();
        return;
      }

      if (!response.ok) {
        throw new Error('Failed to enroll in challenge');
      }

      await loadChallengesAndEnrollments();
    } catch (err) {
      setError(err.message || 'An error occurred during enrollment');
    } finally {
      setEnrollingId(null);
    }
  };

  const filteredChallenges = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return challenges;
    return challenges.filter((c) => (c.title || '').toLowerCase().includes(q));
  }, [challenges, searchQuery]);

  return (
    <div className="challenges-container">
      <div className="challenges-content">
        <h1>Challenges</h1>

        {loading && <p className="loading-message">Loading challenges...</p>}

        {error && <p className="error-message">{error}</p>}

        {!loading && !error && challenges.length === 0 && (
          <p className="no-challenges">No challenges available</p>
        )}

        {!loading && !error && challenges.length > 0 && (
          <div className="challenges-search-row">
            <span className="challenges-search-icon" aria-hidden>
              🔍
            </span>
            <input
              id="challenges-search-input"
              type="search"
              className="challenges-search-input"
              placeholder="Search challenges..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              autoComplete="off"
              aria-label="Search challenges by title"
            />
          </div>
        )}

        {!loading && !error && challenges.length > 0 && filteredChallenges.length === 0 && searchQuery.trim() !== '' && (
          <p className="challenges-search-empty">
            {`No challenges found for '${searchQuery.trim()}'`}
          </p>
        )}

        {!loading && !error && filteredChallenges.length > 0 && (
          <div className="challenges-grid">
            {filteredChallenges.map((challenge) => {
              const enrollment = enrollmentsByChallengeId[challenge.id];
              const isEnrolled = Boolean(enrollment);
              const isComplete =
                isEnrolled &&
                enrollment.required_classes > 0 &&
                enrollment.classes_completed >= enrollment.required_classes;

              return (
                <div
                  key={challenge.id}
                  className={`challenge-card${isComplete ? ' challenge-card--completed' : ''}${
                    !isEnrolled ? ' challenge-card--available' : ''
                  }`}
                  onClick={() => navigate(`/challenges/${challenge.id}`)}
                >
                  {isComplete && (
                    <span className="challenge-badge-completed" aria-label="Challenge completed">
                      ✓ Completed
                    </span>
                  )}
                  <h2
                    className={`challenge-title${isComplete ? ' challenge-title--done challenge-title--with-badge' : ''}`}
                  >
                    {challenge.title}
                  </h2>
                  <p className="challenge-subtitle">
                    {challenge.required_classes} classes · {challenge.points_reward} pts
                  </p>
                  {isEnrolled && !isComplete && (
                    <p className="challenge-classes-progress">
                      {enrollment.classes_completed} / {enrollment.required_classes} classes
                    </p>
                  )}
                  {!isEnrolled ? (
                    <button
                      type="button"
                      className="enroll-button enroll-button--join"
                      onClick={(event) => {
                        event.stopPropagation();
                        handleEnroll(challenge.id);
                      }}
                      disabled={enrollingId === challenge.id}
                    >
                      Join
                    </button>
                  ) : isComplete ? (
                    <span className="enroll-status-completed">Completed ✓</span>
                  ) : (
                    <button type="button" className="enroll-button enroll-button--enrolled" disabled>
                      Enrolled
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <Navbar />
    </div>
  );
}

export default Challenges;
