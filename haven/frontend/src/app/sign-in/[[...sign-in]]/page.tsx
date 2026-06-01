import { SignIn } from '@clerk/nextjs'

export default function SignInPage() {
  return (
    <div style={{
      minHeight: '100vh',
      background: 'linear-gradient(135deg, #fdf2f8 0%, #fce7f3 100%)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <SignIn routing="path" path="/sign-in" />
    </div>
  )
}
