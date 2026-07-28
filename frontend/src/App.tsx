import { Outlet, Route, Routes } from "react-router-dom";
import { Navigation } from "./components/Navigation/Navigation";
import { Landing } from "./pages/Landing/Landing";

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

function KlassePlatzhalter() {
  return <p>Schülerliste folgt in einem späteren Ausbauschritt.</p>;
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Landing />} />
        <Route path="/klasse/:id" element={<KlassePlatzhalter />} />
      </Route>
    </Routes>
  );
}
