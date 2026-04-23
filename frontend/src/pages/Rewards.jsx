import { useState, useEffect } from 'react';
import Navbar from '../components/Navbar';
import './Rewards.css';

function Rewards() {
  const [balance, setBalance] = useState(0);
  const [rewards, setRewards] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  const [claimingId, setClaimingId] = useState(null);

  const fetchRewards = async () => {
    try {
      setLoading(true);
      setError(null);
      const token = localStorage.getItem('token');

      const response = await fetch('http://127.0.0.1:5000/api/rewards', {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        throw new Error('Failed to fetch rewards');
      }

      const data = await response.json();
      setBalance(data.balance || 0);
      setRewards(data.rewards || []);
    } catch (err) {
      setError(err.message || 'An error occurred while fetching rewards');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRewards();
  }, []);

  const handleClaim = async (rewardId) => {
    try {
      setClaimingId(rewardId);
      setSuccessMessage(null);
      const token = localStorage.getItem('token');

      const response = await fetch('http://127.0.0.1:5000/api/redeem', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ reward_id: rewardId }),
      });

      if (!response.ok) {
        throw new Error('Failed to claim reward');
      }

      const data = await response.json();
      setSuccessMessage(`Redeemed! Code: ${data.code}`);

      // Refresh rewards and balance
      await fetchRewards();
    } catch (err) {
      setError(err.message || 'An error occurred during redemption');
    } finally {
      setClaimingId(null);
    }
  };

  return (
    <div className="rewards-container">
      <div className="rewards-content">
        <h1 className="balance-title">Your balance: {balance} pts</h1>

        {loading && <p className="loading-message">Loading rewards...</p>}

        {error && <p className="error-message">{error}</p>}

        {successMessage && (
          <p className="success-message">{successMessage}</p>
        )}

        {!loading && !error && rewards.length === 0 && (
          <p className="no-rewards">No rewards available</p>
        )}

        <div className="rewards-grid">
          {rewards.map((reward) => (
            <div key={reward.id} className="reward-card">
              <h2 className="reward-title">{reward.title}</h2>
              <p className="reward-subtitle">{reward.points_cost} pts</p>
              <button
                className={`claim-button ${!reward.can_afford ? 'disabled' : ''}`}
                onClick={() => handleClaim(reward.id)}
                disabled={!reward.can_afford || claimingId === reward.id}
              >
                {reward.can_afford ? 'Claim' : "Can't afford"}
              </button>
            </div>
          ))}
        </div>
      </div>

      <Navbar />
    </div>
  );
}

export default Rewards;