import { useState, useEffect } from 'react';
import Navbar from '../components/Navbar';
import './Profile.css';

function Profile() {
  const [profileData, setProfileData] = useState({
    name: '',
    email: '',
    created_at: '',
    balance: 0,
    lifetime_points: 0,
    challenges_completed: 0,
    rewards_redeemed: 0
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchProfileData = async () => {
    try {
      setLoading(true);
      setError(null);
      const token = localStorage.getItem('token');

      // Get user info from localStorage
      const name = localStorage.getItem('name') || '';
      const email = localStorage.getItem('email') || '';
      const created_at = localStorage.getItem('created_at') || '';

      // Fetch balance
      const rewardsResponse = await fetch('http://127.0.0.1:5000/api/rewards', {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      const rewardsData = await rewardsResponse.json();

      // Fetch lifetime points
      const lifetimeResponse = await fetch('http://127.0.0.1:5000/api/point_txns/lifetime', {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      const lifetimeData = await lifetimeResponse.json();

      // Fetch profile stats
      const statsResponse = await fetch('http://127.0.0.1:5000/api/profile/stats', {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      const statsData = await statsResponse.json();

      setProfileData({
        name,
        email,
        created_at,
        balance: rewardsData.balance || 0,
        lifetime_points: lifetimeData.lifetime_points || 0,
        challenges_completed: statsData.challenges_completed || 0,
        rewards_redeemed: statsData.rewards_redeemed || 0
      });
    } catch (err) {
      setError(err.message || 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProfileData();
  }, []);

  const getInitials = (name) => {
    return name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2);
  };

  const formatDate = (dateString) => {
    if (!dateString) return '';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric'
    });
  };

  if (loading) {
    return (
      <div className="profile-container">
        <div className="profile-content">
          <p className="loading-message">Loading profile...</p>
        </div>
        <Navbar />
      </div>
    );
  }

  if (error) {
    return (
      <div className="profile-container">
        <div className="profile-content">
          <p className="error-message">{error}</p>
        </div>
        <Navbar />
      </div>
    );
  }

  return (
    <div className="profile-container">
      <div className="profile-content">
        <div className="profile-header">
          <div className="avatar">
            <span className="avatar-text">{getInitials(profileData.name)}</span>
          </div>
          <h1 className="profile-name">{profileData.name}</h1>
          <p className="profile-email">{profileData.email}</p>
        </div>

        <div className="divider"></div>

        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-value">{profileData.balance}</div>
            <div className="stat-label">Current Balance</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{profileData.lifetime_points}</div>
            <div className="stat-label">Lifetime Points</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{profileData.challenges_completed}</div>
            <div className="stat-label">Challenges Completed</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{profileData.rewards_redeemed}</div>
            <div className="stat-label">Rewards Redeemed</div>
          </div>
        </div>

        <p className="member-since">Member since {formatDate(profileData.created_at)}</p>
      </div>

      <Navbar />
    </div>
  );
}

export default Profile;