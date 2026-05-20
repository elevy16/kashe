import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import './Login.css';
import { signInWithPopup } from 'firebase/auth';
import { auth, GoogleAuthProvider } from '../firebase';

const googleProvider = new GoogleAuthProvider();

function clearChatHistoryOnNewLogin() {
  try {
    sessionStorage.removeItem('kashe_chat_history');
    sessionStorage.removeItem('kashe_pending_log_challenge');
  } catch {
    // ignore
  }
}

function Login({ setIsAuthenticated }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [googleBusy, setGoogleBusy] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const response = await fetch('http://127.0.0.1:5000/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim(), password })
      });
      const data = await response.json();
      if (response.ok) {
        clearChatHistoryOnNewLogin();
        localStorage.setItem('token', data.token);
        localStorage.setItem('name', data.name);
        localStorage.setItem('email', data.email);
        localStorage.setItem('created_at', data.created_at);
        setIsAuthenticated(true);
        navigate('/home');
      } else {
        setError(data.error || 'Login failed');
      }
    } catch (err) {
      setError('Network error');
    }
  };

  const handleGoogleSignIn = async () => {
    setError('');
    setGoogleBusy(true);
    try {
      const result = await signInWithPopup(auth, googleProvider);
      const idToken = await result.user.getIdToken();
      const response = await fetch('http://127.0.0.1:5000/api/auth/google', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: idToken }),
      });
      const data = await response.json();
      if (response.ok) {
        clearChatHistoryOnNewLogin();
        localStorage.setItem('token', data.token);
        localStorage.setItem('name', data.name);
        localStorage.setItem('email', data.email);
        localStorage.setItem('created_at', data.created_at);
        setIsAuthenticated(true);
        navigate('/home');
      } else {
        setError(data.error || 'Google sign-in failed');
      }
    } catch (err) {
      if (err?.code === 'auth/popup-closed-by-user') {
        setError('');
      } else {
        setError('Google sign-in failed');
      }
    } finally {
      setGoogleBusy(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <span className="auth-card-logo" aria-hidden>
          ◇
        </span>
        <h1>Login to Kashé</h1>
        <form onSubmit={handleSubmit}>
          <input
            type="text"
            autoComplete="username"
            placeholder="Email or name"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <input type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          <button type="submit">Login</button>
        </form>

        <div className="auth-divider">
          <span className="auth-divider-line" aria-hidden />
          <span className="auth-divider-or">or</span>
          <span className="auth-divider-line" aria-hidden />
        </div>

        <button
          type="button"
          className="auth-google-btn"
          disabled={googleBusy}
          onClick={handleGoogleSignIn}
        >
          <span className="auth-google-icon" aria-hidden>
            G
          </span>
          Sign in with Google
        </button>

        {error && <p className="form-error">{error}</p>}
        <p className="form-footer">
          Don't have an account? <Link to="/register">Register</Link>
        </p>
      </div>
    </div>
  );
}

export default Login;