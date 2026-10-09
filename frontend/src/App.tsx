import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import { useNavOptions } from "./api/hooks/useNavOptions";
import { Navigation } from "./components/Navigation/Navigation";
import { AdminLayout } from "./pages/Admin/AdminLayout";
import { ExcuseStatuses } from "./pages/Admin/ExcuseStatuses";
import { KlassendienstTypen } from "./pages/Admin/KlassendienstTypen";
import { MeasureTypes } from "./pages/Admin/MeasureTypes";
import { SchuljahrImport } from "./pages/Admin/SchuljahrImport";
import { SyncSettings } from "./pages/Admin/SyncSettings";
import { ThresholdRules } from "./pages/Admin/ThresholdRules";
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
        <Route
          path="/admin"
          element={
            <RequireSchulleitung>
              <AdminLayout />
            </RequireSchulleitung>
          }
        >
          <Route index element={<Navigate to="schwellwerte" replace />} />
          <Route path="sync" element={<SyncSettings />} />
          <Route path="schuljahr-import" element={<SchuljahrImport />} />
          <Route path="entschuldigungsstatus" element={<ExcuseStatuses />} />
          <Route path="massnahmen" element={<MeasureTypes />} />
          <Route path="klassendienste" element={<KlassendienstTypen />} />
          <Route path="schwellwerte" element={<ThresholdRules />} />
        </Route>
      </Route>
    </Routes>
  );
}
