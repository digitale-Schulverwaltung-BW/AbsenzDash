import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import { useNavOptions } from "./api/hooks/useNavOptions";
import { Navigation } from "./components/Navigation/Navigation";
import { Landing } from "./pages/Landing/Landing";
import { StudentDetail } from "./pages/StudentDetail/StudentDetail";
import { StudentList } from "./pages/StudentList/StudentList";

function Layout() {
  return (
    <div>
      <Navigation />
      <main>
        <Outlet />
      </main>
    </div>
  );
}

export function RequireSchulleitung({ children }: { children: React.ReactNode }) {
  const { data, isLoading } = useNavOptions();
  if (isLoading) {
    return <p>Lädt…</p>;
  }
  if (data?.rolle !== "schulleitung") {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Landing />} />
        <Route path="/schueler" element={<StudentList />} />
        <Route path="/schueler/:id" element={<StudentDetail />} />
      </Route>
    </Routes>
  );
}
