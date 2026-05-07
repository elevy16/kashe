import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { signInWithPopup } from 'firebase/auth';
import { auth, GoogleAuthProvider } from '../firebase';

const googleProvider = new GoogleAuthProvider();

function Register({ setIsAuthenticated }) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [googleBusy, setGoogleBusy] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const response = await fetch('http://127.0.0.1:5000/api/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          email: email.trim(),
          password,
        }),
      });
      const data = await response.json();
      if (response.ok) {
        navigate('/');
      } else {
        setError(data.error || 'Registration failed');
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
        <h1>Register for Kashé</h1>
        <form onSubmit={handleSubmit}>
          <input type="text" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} required />
          <input type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          <input type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          <button type="submit">Register</button>
        </form>

        <div className="auth-divider">
          <span className="auth-divider-line" aria-hidden />
          <span className="auth-divider-or">or</span>
          <span className="auth-divider-line" aria-hidden />
        </div>

        <button type="button" className="auth-google-btn" disabled={googleBusy} onClick={handleGoogleSignIn}>
          <span className="auth-google-icon" aria-hidden>
            G
          </span>
          Sign in with Google
        </button>

        {error && <p className="form-error">{error}</p>}
        <p className="form-footer">
          Already have an account? <Link to="/">Back to Login</Link>
        </p>
      </div>
    </div>
  );
}

export default Register;
