# Schülerliste, Schüler-Detail, Maßnahmen-/Ausnahmen-Formulare Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Schülerliste (`GET /students`), die Schüler-Detailseite (`GET /students/{id}`), und die Formulare zum Erfassen von Maßnahmen und zum Setzen/Aufheben von Ausnahmen im React/TS-Frontend, inklusive eines neuen rollenoffenen Katalog-Endpunkts im Backend.

**Architecture:** Backend bekommt einen neuen `GET /students/catalog`-Endpunkt (Maßnahmen-Typen, Entschuldigungsstatus, Klassenbuch-Kategorien für alle Rollen). Frontend bekommt neue react-query-Hooks (Lese- und Mutations-Hooks) sowie neue Komponenten/Seiten unter `frontend/src/components/` und `frontend/src/pages/`, eingehängt über zwei neue Routen (`/schueler`, `/schueler/:id`) und zwei Navigation-Tabs.

**Tech Stack:** FastAPI/SQLAlchemy 2.0 (Backend, Python), Vite/React/TypeScript, react-router, @tanstack/react-query, CSS-Module, Vitest + React Testing Library (Frontend).

## Global Constraints

- Backend-Tests: pytest, `db_session`-Fixture, `ASGITransport`/`AsyncClient` gegen `app.main.app`, Header-Dicts wie in bestehenden Tests (`backend/tests/test_api_students.py`, `test_api_admin_measure_types.py`).
- Frontend-Tests: Vitest + React Testing Library, Hooks werden mit `vi.mock(...)` + `vi.mocked(...)` gemockt (nie echte Netzwerkaufrufe in Komponenten-Tests), Rendering immer in `<MemoryRouter>`.
- Kein Component-Framework, reines CSS (CSS-Module) — siehe Plan 9.
- Alle neuen deutschen fachlichen Begriffe (Feldnamen, Routen) folgen der bestehenden Konvention: deutsche Domänenbegriffe (`schueler`, `massnahme`, `ausnahme`), englische technische Namen (`StudentList`, `useStudents`) — konsistent mit den bereits vorhandenen Dateien.
- Jeder Task endet mit einem eigenen Commit.

---

## Task 1: Backend — `GET /students/catalog`-Endpunkt

**Files:**
- Modify: `backend/app/schemas/students.py`
- Modify: `backend/app/services/student_query.py`
- Modify: `backend/app/api/routes/students.py`
- Test: `backend/tests/test_api_students_catalog.py`

**Interfaces:**
- Produces: `StudentCatalogOut` (Pydantic-Schema mit `massnahmen_typen: list[MassnahmenTypCatalogOut]`, `excuse_statuses: list[ExcuseStatusCatalogOut]`, `classreg_categories: list[ClassregCategoryCatalogOut]`), Route `GET /students/catalog` (kein Admin-Check, normale `get_wordpress_proxy_nutzer`-Auth), Query-Funktionen `student_query.load_all_excuse_statuses(db)` und `student_query.load_all_classreg_categories(db)`.

- [ ] **Step 1: Schemas ergänzen**

In `backend/app/schemas/students.py` ans Dateiende anfügen:

```python
class MassnahmenTypCatalogOut(BaseModel):
    id: int
    name: str


class ExcuseStatusCatalogOut(BaseModel):
    id: int
    name: str
    long_name: str | None


class ClassregCategoryCatalogOut(BaseModel):
    id: int
    name: str
    long_name: str | None


class StudentCatalogOut(BaseModel):
    massnahmen_typen: list[MassnahmenTypCatalogOut]
    excuse_statuses: list[ExcuseStatusCatalogOut]
    classreg_categories: list[ClassregCategoryCatalogOut]
```

- [ ] **Step 2: Query-Funktionen ergänzen**

In `backend/app/services/student_query.py` nach `load_classreg_category_map` (nach Zeile 111) einfügen:

```python
async def load_all_excuse_statuses(db: AsyncSession) -> list[ExcuseStatus]:
    """Alle Entschuldigungsstatus-Stammdaten (auch inaktive, da historische
    Fehlzeiten auf einen inzwischen deaktivierten Status verweisen koennen)."""
    result = await db.execute(select(ExcuseStatus).order_by(ExcuseStatus.name))
    return list(result.scalars().all())


async def load_all_classreg_categories(db: AsyncSession) -> list[ClassregCategory]:
    """Alle Klassenbuch-Kategorie-Stammdaten."""
    result = await db.execute(select(ClassregCategory).order_by(ClassregCategory.name))
    return list(result.scalars().all())
```

- [ ] **Step 3: Route ergänzen**

In `backend/app/api/routes/students.py`: Import-Zeile erweitern (`MassnahmenTypCatalogOut`, `ExcuseStatusCatalogOut`, `ClassregCategoryCatalogOut`, `StudentCatalogOut` zu den bestehenden Importen aus `app.schemas.students` hinzufügen). Route **vor** `@router.get("/{schueler_id}")` einfügen (Reihenfolge ist wichtig — sonst matcht `/students/catalog` gegen die `{schueler_id}`-Route und scheitert an der `int`-Konvertierung):

```python
@router.get("/catalog")
async def get_student_catalog(
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StudentCatalogOut:
    typen = (
        await db.execute(select(MassnahmenTyp).where(MassnahmenTyp.aktiv.is_(True)).order_by(MassnahmenTyp.name))
    ).scalars().all()
    excuse_statuses = await student_query.load_all_excuse_statuses(db)
    classreg_categories = await student_query.load_all_classreg_categories(db)
    return StudentCatalogOut(
        massnahmen_typen=[MassnahmenTypCatalogOut(id=typ.id, name=typ.name) for typ in typen],
        excuse_statuses=[
            ExcuseStatusCatalogOut(id=s.id, name=s.name, long_name=s.long_name) for s in excuse_statuses
        ],
        classreg_categories=[
            ClassregCategoryCatalogOut(id=c.id, name=c.name, long_name=c.long_name) for c in classreg_categories
        ],
    )
```

Der `nutzer`-Parameter wird nicht weiter benutzt außer zur Auth-Prüfung durch die Dependency selbst — das ist konsistent mit anderen ungefilterten Routen in dieser Datei nicht der Fall, aber hier bewusst, da der Endpunkt keinen Scope-Bezug hat (reine Stammdaten).

- [ ] **Step 4: Test schreiben**

Erstelle `backend/tests/test_api_students_catalog.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app
from app.models.classreg_category import ClassregCategory
from app.models.excuse_status import ExcuseStatus
from app.models.massnahmen_typ import MassnahmenTyp

HEADERS_KLASSENLEHRKRAFT = {
    "X-WordPress-Secret": "test-secret",
    "X-WordPress-User": "jseyfried",
    "X-WordPress-Email": "joerg.seyfried@hhs.karlsruhe.de",
    "X-WordPress-Name": "Joerg Seyfried",
    "X-WordPress-Role": "klassenlehrkraft",
}


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setattr(settings, "wordpress_proxy_secret", "test-secret")


@pytest.mark.asyncio
async def test_get_catalog_accessible_for_non_schulleitung_role(db_session):
    aktiv_typ = MassnahmenTyp(name="Gespräch", setzt_zaehler_zurueck=False, aktiv=True)
    inaktiv_typ = MassnahmenTyp(name="Alt", setzt_zaehler_zurueck=False, aktiv=False)
    status = ExcuseStatus(name="E", long_name="Entschuldigt", zaehlt_als_entschuldigt=True, aktiv=True)
    kategorie = ClassregCategory(name="LSU", long_name="Lehrstoffunterbrechung")
    db_session.add_all([aktiv_typ, inaktiv_typ, status, kategorie])
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/students/catalog", headers=HEADERS_KLASSENLEHRKRAFT)

    assert response.status_code == 200
    body = response.json()
    assert [t["name"] for t in body["massnahmen_typen"]] == ["Gespräch"]
    assert body["excuse_statuses"] == [{"id": status.id, "name": "E", "long_name": "Entschuldigt"}]
    assert body["classreg_categories"] == [
        {"id": kategorie.id, "name": "LSU", "long_name": "Lehrstoffunterbrechung"}
    ]


@pytest.mark.asyncio
async def test_get_catalog_rejects_missing_wordpress_secret():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/students/catalog", headers={**HEADERS_KLASSENLEHRKRAFT, "X-WordPress-Secret": "wrong"}
        )
    assert response.status_code == 401
```

- [ ] **Step 5: Tests ausführen**

Run: `cd backend && python -m pytest tests/test_api_students_catalog.py -v`
Expected: beide Tests PASS.

- [ ] **Step 6: Vollen Backend-Testlauf prüfen**

Run: `cd backend && python -m pytest -q`
Expected: alle Tests PASS (insbesondere `test_api_students.py` weiterhin grün — die neue Route darf `/students/{schueler_id}` nicht verdecken).

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/students.py backend/app/services/student_query.py backend/app/api/routes/students.py backend/tests/test_api_students_catalog.py
git commit -m "feat: add GET /students/catalog endpoint for measure types, excuse statuses, classreg categories"
```

---

## Task 2: Frontend — API-Client-Mutationen (`apiPost`, `apiDelete`)

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/client.test.ts`

**Interfaces:**
- Consumes: bestehendes `ApiError`, `getConfig()` (intern in `client.ts`).
- Produces: `apiPost<T>(path: string, body: unknown): Promise<T>`, `apiDelete(path: string): Promise<void>`.

- [ ] **Step 1: Failing Tests schreiben**

In `frontend/src/api/client.test.ts` Import-Zeile erweitern (`ApiError, apiDelete, apiGet, apiPost`) und folgende Tests ergänzen:

```ts
describe("apiPost", () => {
  it("sends the nonce header, JSON content-type and body, returns the parsed response", async () => {
    window.absenzdashConfig = {
      restUrl: "https://example.test/wp-json/absenzdash/v1/api",
      nonce: "abc123",
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 1 }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await apiPost<{ id: number }>("students/1/measures", { massnahmen_typ_id: 2 });

    expect(result).toEqual({ id: 1 });
    expect(fetchMock).toHaveBeenCalledWith(
      "https://example.test/wp-json/absenzdash/v1/api/students/1/measures",
      {
        method: "POST",
        headers: { "X-WP-Nonce": "abc123", "Content-Type": "application/json" },
        body: JSON.stringify({ massnahmen_typ_id: 2 }),
      },
    );
  });

  it("throws an ApiError when the response is not ok", async () => {
    window.absenzdashConfig = {
      restUrl: "https://example.test/wp-json/absenzdash/v1/api",
      nonce: "abc123",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 422 })));

    await expect(apiPost("students/1/measures", {})).rejects.toBeInstanceOf(ApiError);
  });
});

describe("apiDelete", () => {
  it("sends the nonce header and resolves without a body on success", async () => {
    window.absenzdashConfig = {
      restUrl: "https://example.test/wp-json/absenzdash/v1/api",
      nonce: "abc123",
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiDelete("students/1/exemptions/2")).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      "https://example.test/wp-json/absenzdash/v1/api/students/1/exemptions/2",
      { method: "DELETE", headers: { "X-WP-Nonce": "abc123" } },
    );
  });

  it("throws an ApiError when the response is not ok", async () => {
    window.absenzdashConfig = {
      restUrl: "https://example.test/wp-json/absenzdash/v1/api",
      nonce: "abc123",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 404 })));

    await expect(apiDelete("students/1/exemptions/2")).rejects.toBeInstanceOf(ApiError);
  });
});
```

- [ ] **Step 2: Tests ausführen, Fehlschlag prüfen**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: FAIL mit `apiPost`/`apiDelete` is not exported/not defined.

- [ ] **Step 3: Implementierung**

In `frontend/src/api/client.ts` ans Dateiende anfügen:

```ts
export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const config = getConfig();
  const response = await fetch(`${config.restUrl}/${path}`, {
    method: "POST",
    headers: { "X-WP-Nonce": config.nonce, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new ApiError(response.status, `POST ${path} failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function apiDelete(path: string): Promise<void> {
  const config = getConfig();
  const response = await fetch(`${config.restUrl}/${path}`, {
    method: "DELETE",
    headers: { "X-WP-Nonce": config.nonce },
  });
  if (!response.ok) {
    throw new ApiError(response.status, `DELETE ${path} failed with status ${response.status}`);
  }
}
```

- [ ] **Step 4: Tests ausführen, Erfolg prüfen**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: alle Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/api/client.test.ts
git commit -m "feat: add apiPost and apiDelete to the frontend API client"
```

---

## Task 3: Frontend — Typen und Lese-Hooks (Katalog, Liste, Detail)

**Files:**
- Modify: `frontend/src/api/types.ts`
- Create: `frontend/src/api/hooks/useStudentCatalog.ts`
- Create: `frontend/src/api/hooks/useStudentCatalog.test.ts`
- Create: `frontend/src/api/hooks/useStudents.ts`
- Create: `frontend/src/api/hooks/useStudents.test.ts`
- Create: `frontend/src/api/hooks/useStudentDetail.ts`
- Create: `frontend/src/api/hooks/useStudentDetail.test.ts`

**Interfaces:**
- Consumes: `apiGet` aus `../client` (bestehend).
- Produces (Typen in `types.ts`): `Klasse`, `Zaehlerstand`, `BenachrichtigungEmpfaenger`, `Benachrichtigung`, `StudentOverview`, `StudentList`, `Fehlzeit`, `KlassenbuchEintrag`, `Massnahme`, `Ausnahme`, `StudentDetail`, `MassnahmenTyp`, `ExcuseStatusCatalogEntry`, `ClassregCategoryCatalogEntry`, `StudentCatalog`.
- Produces (Hooks): `useStudentCatalog()`, `useStudents(params: StudentListParams)` mit `StudentListParams { bereichId, klasseId, minStufe, nurAuffaellige, offset }`, `STUDENT_LIST_LIMIT` (Konstante `50`), `useStudentDetail(studentId: number)`, `studentDetailQueryKey(studentId: number)` (wird in Task 4 für Cache-Invalidierung gebraucht).

- [ ] **Step 1: Typen ergänzen**

In `frontend/src/api/types.ts` ans Dateiende anfügen:

```ts
export interface Klasse {
  id: number;
  name: string;
}

export interface Zaehlerstand {
  aktueller_stand: number;
  erreichte_stufe_nr: number | null;
}

export interface BenachrichtigungEmpfaenger {
  rolle: string;
  name?: string;
  [key: string]: unknown;
}

export interface Benachrichtigung {
  id: number;
  regel_id: number | null;
  typ: string | null;
  stufe_nr: number;
  gesendet_am: string;
  empfaenger: BenachrichtigungEmpfaenger[];
  status: string;
}

export interface StudentOverview {
  id: number;
  vorname: string;
  nachname: string;
  klasse: Klasse | null;
  zaehlerstand: Record<string, Zaehlerstand>;
  letzte_benachrichtigung: Benachrichtigung | null;
  ohne_massnahme_seit_benachrichtigung: boolean;
}

export interface StudentList {
  items: StudentOverview[];
  total: number;
  limit: number;
  offset: number;
}

export interface Fehlzeit {
  id: number;
  typ: string;
  datum: string;
  start_zeit: number;
  end_zeit: number;
  fach: string | null;
  excuse_status_id: number | null;
  grund_text: string | null;
}

export interface KlassenbuchEintrag {
  id: number;
  kategorie_id: number;
  datum: string;
  text: string | null;
  lesson_id: number | null;
}

export interface Massnahme {
  id: number;
  massnahmen_typ_id: number;
  massnahmen_typ_name: string;
  datum: string;
  notiz: string | null;
  erfasst_von_nutzer_id: number;
  erfasst_von_name: string;
}

export interface Ausnahme {
  id: number;
  kategorie: "fehlzeiten" | "klassenbuch";
  grund: string;
  gueltig_bis: string | null;
  aktiv: boolean;
}

export interface StudentDetail {
  id: number;
  vorname: string;
  nachname: string;
  klasse: Klasse | null;
  zaehlerstand: Record<string, Zaehlerstand>;
  fehlzeiten: Fehlzeit[];
  klassenbuch: KlassenbuchEintrag[];
  massnahmen: Massnahme[];
  ausnahmen: Ausnahme[];
  benachrichtigungen: Benachrichtigung[];
}

export interface MassnahmenTyp {
  id: number;
  name: string;
}

export interface ExcuseStatusCatalogEntry {
  id: number;
  name: string;
  long_name: string | null;
}

export interface ClassregCategoryCatalogEntry {
  id: number;
  name: string;
  long_name: string | null;
}

export interface StudentCatalog {
  massnahmen_typen: MassnahmenTyp[];
  excuse_statuses: ExcuseStatusCatalogEntry[];
  classreg_categories: ClassregCategoryCatalogEntry[];
}
```

- [ ] **Step 2: `useStudentCatalog`-Test schreiben**

Erstelle `frontend/src/api/hooks/useStudentCatalog.test.ts`:

```ts
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { useStudentCatalog } from "./useStudentCatalog";

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useStudentCatalog", () => {
  it("fetches students/catalog", async () => {
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue({
      massnahmen_typen: [],
      excuse_statuses: [],
      classreg_categories: [],
    });

    const { result } = renderHook(() => useStudentCatalog(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("students/catalog");
  });
});
```

- [ ] **Step 3: `useStudentCatalog` implementieren**

Erstelle `frontend/src/api/hooks/useStudentCatalog.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { StudentCatalog } from "../types";

export function useStudentCatalog() {
  return useQuery({
    queryKey: ["student-catalog"],
    queryFn: () => apiGet<StudentCatalog>("students/catalog"),
    staleTime: 5 * 60 * 1000,
  });
}
```

- [ ] **Step 4: `useStudents`-Test schreiben**

Erstelle `frontend/src/api/hooks/useStudents.test.ts`:

```ts
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { useStudents } from "./useStudents";

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useStudents", () => {
  it("builds the query string from the given filter params", async () => {
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });

    const { result } = renderHook(
      () => useStudents({ bereichId: 3, klasseId: null, minStufe: 2, nurAuffaellige: true, offset: 50 }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("students?bereich_id=3&min_stufe=2&nur_auffaellige=true&offset=50");
  });

  it("omits unset filters", async () => {
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });

    const { result } = renderHook(
      () => useStudents({ bereichId: null, klasseId: null, minStufe: null, nurAuffaellige: false, offset: 0 }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("students?offset=0");
  });
});
```

- [ ] **Step 5: `useStudents` implementieren**

Erstelle `frontend/src/api/hooks/useStudents.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { StudentList } from "../types";

export const STUDENT_LIST_LIMIT = 50;

export interface StudentListParams {
  bereichId: number | null;
  klasseId: number | null;
  minStufe: number | null;
  nurAuffaellige: boolean;
  offset: number;
}

function buildQuery(params: StudentListParams): string {
  const query = new URLSearchParams();
  if (params.bereichId !== null) query.set("bereich_id", String(params.bereichId));
  if (params.klasseId !== null) query.set("klasse_id", String(params.klasseId));
  if (params.minStufe !== null) query.set("min_stufe", String(params.minStufe));
  if (params.nurAuffaellige) query.set("nur_auffaellige", "true");
  query.set("offset", String(params.offset));
  return query.toString();
}

export function useStudents(params: StudentListParams) {
  return useQuery({
    queryKey: ["students", params],
    queryFn: () => apiGet<StudentList>(`students?${buildQuery(params)}`),
  });
}
```

- [ ] **Step 6: `useStudentDetail`-Test schreiben**

Erstelle `frontend/src/api/hooks/useStudentDetail.test.ts`:

```ts
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { studentDetailQueryKey, useStudentDetail } from "./useStudentDetail";

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useStudentDetail", () => {
  it("fetches students/:id and uses studentDetailQueryKey as its query key", async () => {
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue({ id: 7 });

    const { result } = renderHook(() => useStudentDetail(7), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("students/7");
    expect(studentDetailQueryKey(7)).toEqual(["student-detail", 7]);
  });
});
```

- [ ] **Step 7: `useStudentDetail` implementieren**

Erstelle `frontend/src/api/hooks/useStudentDetail.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { StudentDetail } from "../types";

export function studentDetailQueryKey(studentId: number) {
  return ["student-detail", studentId] as const;
}

export function useStudentDetail(studentId: number) {
  return useQuery({
    queryKey: studentDetailQueryKey(studentId),
    queryFn: () => apiGet<StudentDetail>(`students/${studentId}`),
  });
}
```

- [ ] **Step 8: Tests ausführen**

Run: `cd frontend && npx vitest run src/api/hooks/useStudentCatalog.test.ts src/api/hooks/useStudents.test.ts src/api/hooks/useStudentDetail.test.ts`
Expected: alle Tests PASS.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/hooks/useStudentCatalog.ts frontend/src/api/hooks/useStudentCatalog.test.ts frontend/src/api/hooks/useStudents.ts frontend/src/api/hooks/useStudents.test.ts frontend/src/api/hooks/useStudentDetail.ts frontend/src/api/hooks/useStudentDetail.test.ts
git commit -m "feat: add types and read hooks for student catalog, list, and detail"
```

---

## Task 4: Frontend — Mutations-Hooks (Maßnahme anlegen, Ausnahme anlegen/aufheben)

**Files:**
- Create: `frontend/src/api/hooks/useCreateMeasure.ts`
- Create: `frontend/src/api/hooks/useCreateMeasure.test.ts`
- Create: `frontend/src/api/hooks/useCreateExemption.ts`
- Create: `frontend/src/api/hooks/useCreateExemption.test.ts`
- Create: `frontend/src/api/hooks/useRevokeExemption.ts`
- Create: `frontend/src/api/hooks/useRevokeExemption.test.ts`

**Interfaces:**
- Consumes: `apiPost`, `apiDelete` (Task 2), `studentDetailQueryKey` (Task 3), Typen `Massnahme`, `Ausnahme` (Task 3).
- Produces: `useCreateMeasure(studentId: number)` → react-query `useMutation` mit `mutate(input: CreateMeasureInput)`, `CreateMeasureInput { massnahmen_typ_id: number; datum: string; notiz: string | null }`. `useCreateExemption(studentId: number)` → `mutate(input: CreateExemptionInput)`, `CreateExemptionInput { kategorie: "fehlzeiten" | "klassenbuch"; grund: string; gueltig_bis: string | null }`. `useRevokeExemption(studentId: number)` → `mutate(exemptionId: number)`.

- [ ] **Step 1: Tests schreiben**

Erstelle `frontend/src/api/hooks/useCreateMeasure.test.ts`:

```ts
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { useCreateMeasure } from "./useCreateMeasure";

describe("useCreateMeasure", () => {
  it("posts to students/:id/measures and invalidates the student detail query", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    const postSpy = vi.spyOn(client, "apiPost").mockResolvedValue({ id: 1 });

    function wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
    }

    const { result } = renderHook(() => useCreateMeasure(7), { wrapper });
    result.current.mutate({ massnahmen_typ_id: 2, datum: "2026-07-28", notiz: null });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(postSpy).toHaveBeenCalledWith("students/7/measures", {
      massnahmen_typ_id: 2,
      datum: "2026-07-28",
      notiz: null,
    });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["student-detail", 7] });
  });
});
```

Erstelle `frontend/src/api/hooks/useCreateExemption.test.ts`:

```ts
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { useCreateExemption } from "./useCreateExemption";

describe("useCreateExemption", () => {
  it("posts to students/:id/exemptions and invalidates the student detail query", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    const postSpy = vi.spyOn(client, "apiPost").mockResolvedValue({ id: 1 });

    function wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
    }

    const { result } = renderHook(() => useCreateExemption(7), { wrapper });
    result.current.mutate({ kategorie: "fehlzeiten", grund: "Attest", gueltig_bis: null });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(postSpy).toHaveBeenCalledWith("students/7/exemptions", {
      kategorie: "fehlzeiten",
      grund: "Attest",
      gueltig_bis: null,
    });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["student-detail", 7] });
  });
});
```

Erstelle `frontend/src/api/hooks/useRevokeExemption.test.ts`:

```ts
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { useRevokeExemption } from "./useRevokeExemption";

describe("useRevokeExemption", () => {
  it("deletes students/:id/exemptions/:exemptionId and invalidates the student detail query", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    const deleteSpy = vi.spyOn(client, "apiDelete").mockResolvedValue(undefined);

    function wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
    }

    const { result } = renderHook(() => useRevokeExemption(7), { wrapper });
    result.current.mutate(3);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(deleteSpy).toHaveBeenCalledWith("students/7/exemptions/3");
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["student-detail", 7] });
  });
});
```

- [ ] **Step 2: Tests ausführen, Fehlschlag prüfen**

Run: `cd frontend && npx vitest run src/api/hooks/useCreateMeasure.test.ts src/api/hooks/useCreateExemption.test.ts src/api/hooks/useRevokeExemption.test.ts`
Expected: FAIL (Module nicht gefunden).

- [ ] **Step 3: Implementierung**

Erstelle `frontend/src/api/hooks/useCreateMeasure.ts`:

```ts
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPost } from "../client";
import type { Massnahme } from "../types";
import { studentDetailQueryKey } from "./useStudentDetail";

export interface CreateMeasureInput {
  massnahmen_typ_id: number;
  datum: string;
  notiz: string | null;
}

export function useCreateMeasure(studentId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateMeasureInput) => apiPost<Massnahme>(`students/${studentId}/measures`, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: studentDetailQueryKey(studentId) });
    },
  });
}
```

Erstelle `frontend/src/api/hooks/useCreateExemption.ts`:

```ts
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPost } from "../client";
import type { Ausnahme } from "../types";
import { studentDetailQueryKey } from "./useStudentDetail";

export interface CreateExemptionInput {
  kategorie: "fehlzeiten" | "klassenbuch";
  grund: string;
  gueltig_bis: string | null;
}

export function useCreateExemption(studentId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateExemptionInput) => apiPost<Ausnahme>(`students/${studentId}/exemptions`, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: studentDetailQueryKey(studentId) });
    },
  });
}
```

Erstelle `frontend/src/api/hooks/useRevokeExemption.ts`:

```ts
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiDelete } from "../client";
import { studentDetailQueryKey } from "./useStudentDetail";

export function useRevokeExemption(studentId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (exemptionId: number) => apiDelete(`students/${studentId}/exemptions/${exemptionId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: studentDetailQueryKey(studentId) });
    },
  });
}
```

- [ ] **Step 4: Tests ausführen, Erfolg prüfen**

Run: `cd frontend && npx vitest run src/api/hooks/useCreateMeasure.test.ts src/api/hooks/useCreateExemption.test.ts src/api/hooks/useRevokeExemption.test.ts`
Expected: alle Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/hooks/useCreateMeasure.ts frontend/src/api/hooks/useCreateMeasure.test.ts frontend/src/api/hooks/useCreateExemption.ts frontend/src/api/hooks/useCreateExemption.test.ts frontend/src/api/hooks/useRevokeExemption.ts frontend/src/api/hooks/useRevokeExemption.test.ts
git commit -m "feat: add mutation hooks for creating measures and creating/revoking exemptions"
```

---

## Task 5: Frontend — `StatusBadge`-Komponente

**Files:**
- Create: `frontend/src/components/StatusBadge/StatusBadge.tsx`
- Create: `frontend/src/components/StatusBadge/StatusBadge.module.css`
- Create: `frontend/src/components/StatusBadge/StatusBadge.test.tsx`

**Interfaces:**
- Produces: `StatusBadge({ label, tone }: { label: string; tone: "neutral" | "info" | "stufe1" | "stufe2" | "stufe3" })`, `export function stufeToTone(stufeNr: number | null): "neutral" | "stufe1" | "stufe2" | "stufe3"` (Hilfsfunktion, wird von Task 7/12 zur Umrechnung von `erreichte_stufe_nr` benutzt).

- [ ] **Step 1: Test schreiben**

Erstelle `frontend/src/components/StatusBadge/StatusBadge.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusBadge, stufeToTone } from "./StatusBadge";

describe("StatusBadge", () => {
  it("renders the given label", () => {
    render(<StatusBadge label="Stufe 2" tone="stufe2" />);
    expect(screen.getByText("Stufe 2")).toBeInTheDocument();
  });
});

describe("stufeToTone", () => {
  it("maps null to neutral and stufe numbers to their tone, capping at stufe3", () => {
    expect(stufeToTone(null)).toBe("neutral");
    expect(stufeToTone(1)).toBe("stufe1");
    expect(stufeToTone(2)).toBe("stufe2");
    expect(stufeToTone(3)).toBe("stufe3");
    expect(stufeToTone(5)).toBe("stufe3");
  });
});
```

- [ ] **Step 2: Test ausführen, Fehlschlag prüfen**

Run: `cd frontend && npx vitest run src/components/StatusBadge/StatusBadge.test.tsx`
Expected: FAIL (Modul existiert nicht).

- [ ] **Step 3: Implementierung**

Erstelle `frontend/src/components/StatusBadge/StatusBadge.module.css`:

```css
.badge {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  font-size: 0.8rem;
  font-weight: 600;
}

.neutral {
  background: #eee;
  color: #555;
}

.info {
  background: #dbeafe;
  color: #1e40af;
}

.stufe1 {
  background: #fef3c7;
  color: #92400e;
}

.stufe2 {
  background: #fed7aa;
  color: #9a3412;
}

.stufe3 {
  background: #fecaca;
  color: #991b1b;
}
```

Erstelle `frontend/src/components/StatusBadge/StatusBadge.tsx`:

```tsx
import styles from "./StatusBadge.module.css";

export type StatusBadgeTone = "neutral" | "info" | "stufe1" | "stufe2" | "stufe3";

interface StatusBadgeProps {
  label: string;
  tone: StatusBadgeTone;
}

export function StatusBadge({ label, tone }: StatusBadgeProps) {
  return <span className={`${styles.badge} ${styles[tone]}`}>{label}</span>;
}

export function stufeToTone(stufeNr: number | null): "neutral" | "stufe1" | "stufe2" | "stufe3" {
  if (stufeNr === null || stufeNr < 1) return "neutral";
  if (stufeNr === 1) return "stufe1";
  if (stufeNr === 2) return "stufe2";
  return "stufe3";
}
```

- [ ] **Step 4: Test ausführen, Erfolg prüfen**

Run: `cd frontend && npx vitest run src/components/StatusBadge/StatusBadge.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/StatusBadge/
git commit -m "feat: add StatusBadge component for Zaehlerstand/Benachrichtigt indicators"
```

---

## Task 6: Frontend — `NotificationFlyout`-Komponente

**Files:**
- Create: `frontend/src/components/NotificationFlyout/NotificationFlyout.tsx`
- Create: `frontend/src/components/NotificationFlyout/NotificationFlyout.module.css`
- Create: `frontend/src/components/NotificationFlyout/NotificationFlyout.test.tsx`

**Interfaces:**
- Consumes: `StatusBadge` (Task 5), Typ `Benachrichtigung` (Task 3).
- Produces: `NotificationFlyout({ benachrichtigung }: { benachrichtigung: Benachrichtigung | null })`.

- [ ] **Step 1: Test schreiben**

Erstelle `frontend/src/components/NotificationFlyout/NotificationFlyout.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NotificationFlyout } from "./NotificationFlyout";

describe("NotificationFlyout", () => {
  it("shows a neutral badge and no flyout content when there is no notification", () => {
    render(<NotificationFlyout benachrichtigung={null} />);
    expect(screen.getByText("Keine Benachrichtigung")).toBeInTheDocument();
  });

  it("lists recipients for a sent notification", () => {
    render(
      <NotificationFlyout
        benachrichtigung={{
          id: 1,
          regel_id: 1,
          typ: "fehlzeiten",
          stufe_nr: 1,
          gesendet_am: "2026-02-01T00:00:00Z",
          empfaenger: [{ rolle: "klassenlehrkraft", name: "A. Beispiel" }],
          status: "gesendet",
        }}
      />,
    );
    expect(screen.getByText("Benachrichtigt")).toBeInTheDocument();
    expect(screen.getByText("klassenlehrkraft: A. Beispiel")).toBeInTheDocument();
  });

  it("shows a status text instead of recipients when no recipient could be determined", () => {
    render(
      <NotificationFlyout
        benachrichtigung={{
          id: 1,
          regel_id: 1,
          typ: "fehlzeiten",
          stufe_nr: 1,
          gesendet_am: "2026-02-01T00:00:00Z",
          empfaenger: [],
          status: "kein_empfaenger",
        }}
      />,
    );
    expect(screen.getByText("Kein Empfänger ermittelbar")).toBeInTheDocument();
  });

  it("shows a status text for notifications carried over from the initial import", () => {
    render(
      <NotificationFlyout
        benachrichtigung={{
          id: 1,
          regel_id: 1,
          typ: "fehlzeiten",
          stufe_nr: 1,
          gesendet_am: "2026-02-01T00:00:00Z",
          empfaenger: [],
          status: "initial_import",
        }}
      />,
    );
    expect(screen.getByText("Aus initialem Datenimport übernommen")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Test ausführen, Fehlschlag prüfen**

Run: `cd frontend && npx vitest run src/components/NotificationFlyout/NotificationFlyout.test.tsx`
Expected: FAIL (Modul existiert nicht).

- [ ] **Step 3: Implementierung**

Erstelle `frontend/src/components/NotificationFlyout/NotificationFlyout.module.css`:

```css
.wrapper {
  position: relative;
  display: inline-block;
}

.flyout {
  display: none;
  position: absolute;
  z-index: 10;
  top: 100%;
  left: 0;
  min-width: 12rem;
  padding: 0.5rem;
  background: white;
  border: 1px solid #ccc;
  border-radius: 4px;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);
}

.wrapper:hover .flyout,
.wrapper:focus-within .flyout {
  display: block;
}

.flyout ul {
  margin: 0;
  padding-left: 1rem;
}
```

Erstelle `frontend/src/components/NotificationFlyout/NotificationFlyout.tsx`:

```tsx
import type { Benachrichtigung } from "../../api/types";
import { StatusBadge } from "../StatusBadge/StatusBadge";
import styles from "./NotificationFlyout.module.css";

interface NotificationFlyoutProps {
  benachrichtigung: Benachrichtigung | null;
}

const STATUS_TEXT: Record<string, string> = {
  kein_empfaenger: "Kein Empfänger ermittelbar",
  initial_import: "Aus initialem Datenimport übernommen",
};

export function NotificationFlyout({ benachrichtigung }: NotificationFlyoutProps) {
  if (benachrichtigung === null) {
    return <StatusBadge label="Keine Benachrichtigung" tone="neutral" />;
  }

  const hatEmpfaenger = benachrichtigung.empfaenger.length > 0;

  return (
    <span className={styles.wrapper} tabIndex={0}>
      <StatusBadge label="Benachrichtigt" tone="info" />
      <div className={styles.flyout} role="tooltip">
        {hatEmpfaenger ? (
          <ul>
            {benachrichtigung.empfaenger.map((empfaenger, index) => (
              <li key={index}>
                {empfaenger.name ? `${empfaenger.rolle}: ${empfaenger.name}` : empfaenger.rolle}
              </li>
            ))}
          </ul>
        ) : (
          <p>{STATUS_TEXT[benachrichtigung.status] ?? benachrichtigung.status}</p>
        )}
      </div>
    </span>
  );
}
```

- [ ] **Step 4: Test ausführen, Erfolg prüfen**

Run: `cd frontend && npx vitest run src/components/NotificationFlyout/NotificationFlyout.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/NotificationFlyout/
git commit -m "feat: add NotificationFlyout component for the Benachrichtigt badge"
```

---

## Task 7: Frontend — `StudentList`-Seite

**Files:**
- Create: `frontend/src/pages/StudentList/StudentList.tsx`
- Create: `frontend/src/pages/StudentList/StudentList.module.css`
- Create: `frontend/src/pages/StudentList/StudentList.test.tsx`

**Interfaces:**
- Consumes: `useStudents`, `StudentListParams` (Task 3), `StatusBadge`, `stufeToTone` (Task 5), `NotificationFlyout` (Task 6).
- Produces: `StudentList` (default export, React-Komponente ohne Props — liest Filter aus `useSearchParams`).

- [ ] **Step 1: Test schreiben**

Erstelle `frontend/src/pages/StudentList/StudentList.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useStudents } from "../../api/hooks/useStudents";
import { StudentList } from "./StudentList";

vi.mock("../../api/hooks/useStudents");

const mockUseStudents = vi.mocked(useStudents);

function renderList(initialEntries: string[] = ["/schueler"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <StudentList />
    </MemoryRouter>,
  );
}

const BASE_STUDENT = {
  id: 1,
  vorname: "Max",
  nachname: "Muster",
  klasse: { id: 1, name: "10a" },
  zaehlerstand: {
    fehlzeiten: { aktueller_stand: 4, erreichte_stufe_nr: 1 },
    klassenbuch: { aktueller_stand: 0, erreichte_stufe_nr: null },
  },
  letzte_benachrichtigung: null,
  ohne_massnahme_seit_benachrichtigung: false,
};

describe("StudentList", () => {
  it("renders a row per student with a link to the detail page", () => {
    mockUseStudents.mockReturnValue({
      data: { items: [BASE_STUDENT], total: 1, limit: 50, offset: 0 },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderList();

    expect(screen.getByRole("link", { name: /Muster, Max/ })).toHaveAttribute("href", "/schueler/1");
    expect(screen.getByText("10a")).toBeInTheDocument();
  });

  it("highlights a row without a measure since the last notification", () => {
    mockUseStudents.mockReturnValue({
      data: {
        items: [{ ...BASE_STUDENT, ohne_massnahme_seit_benachrichtigung: true }],
        total: 1,
        limit: 50,
        offset: 0,
      },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderList();

    expect(screen.getByRole("row", { name: /Muster, Max/ })).toHaveAttribute("data-highlighted", "true");
  });

  it("toggles the nur_auffaellige filter via the URL params", () => {
    mockUseStudents.mockReturnValue({
      data: { items: [], total: 0, limit: 50, offset: 0 },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderList();
    fireEvent.click(screen.getByLabelText("Nur auffällige"));

    expect(mockUseStudents).toHaveBeenLastCalledWith(
      expect.objectContaining({ nurAuffaellige: true }),
    );
  });

  it("disables the Weiter button on the last page", () => {
    mockUseStudents.mockReturnValue({
      data: { items: [BASE_STUDENT], total: 1, limit: 50, offset: 0 },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderList();

    expect(screen.getByRole("button", { name: "Weiter" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Zurück" })).toBeDisabled();
  });

  it("shows an error message when the request fails", () => {
    mockUseStudents.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderList();

    expect(screen.getByText("Fehler beim Laden der Schülerliste.")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Test ausführen, Fehlschlag prüfen**

Run: `cd frontend && npx vitest run src/pages/StudentList/StudentList.test.tsx`
Expected: FAIL (Modul existiert nicht).

- [ ] **Step 3: Implementierung**

Erstelle `frontend/src/pages/StudentList/StudentList.module.css`:

```css
.filters {
  display: flex;
  gap: 1rem;
  align-items: center;
  padding: 0.5rem 0;
}

.table {
  width: 100%;
  border-collapse: collapse;
}

.table th,
.table td {
  text-align: left;
  padding: 0.4rem 0.75rem;
  border-bottom: 1px solid #eee;
}

.highlighted {
  border-left: 4px solid #dc2626;
}

.badges {
  display: flex;
  gap: 0.35rem;
  flex-wrap: wrap;
}

.pagination {
  display: flex;
  gap: 0.75rem;
  align-items: center;
  padding-top: 0.75rem;
}
```

Erstelle `frontend/src/pages/StudentList/StudentList.tsx`:

```tsx
import { Link, useSearchParams } from "react-router-dom";
import { useStudents } from "../../api/hooks/useStudents";
import { NotificationFlyout } from "../../components/NotificationFlyout/NotificationFlyout";
import { StatusBadge, stufeToTone } from "../../components/StatusBadge/StatusBadge";
import styles from "./StudentList.module.css";

const ZAEHLERSTAND_LABEL: Record<string, string> = {
  fehlzeiten: "Fehlzeiten",
  klassenbuch: "Klassenbuch",
};

export function StudentList() {
  const [searchParams, setSearchParams] = useSearchParams();

  const bereichParam = searchParams.get("bereich");
  const klasseParam = searchParams.get("klasse");
  const minStufeParam = searchParams.get("min_stufe");
  const nurAuffaellige = searchParams.get("nur_auffaellige") === "true";
  const offset = Number(searchParams.get("offset") ?? "0");

  const { data, isLoading, isError } = useStudents({
    bereichId: bereichParam ? Number(bereichParam) : null,
    klasseId: klasseParam ? Number(klasseParam) : null,
    minStufe: minStufeParam ? Number(minStufeParam) : null,
    nurAuffaellige,
    offset,
  });

  function updateParam(name: string, value: string) {
    const next = new URLSearchParams(searchParams);
    if (value === "") {
      next.delete(name);
    } else {
      next.set(name, value);
    }
    next.delete("offset");
    setSearchParams(next);
  }

  function goToOffset(newOffset: number) {
    const next = new URLSearchParams(searchParams);
    next.set("offset", String(newOffset));
    setSearchParams(next);
  }

  if (isLoading) {
    return <p>Lädt Schülerliste…</p>;
  }
  if (isError || !data) {
    return <p>Fehler beim Laden der Schülerliste.</p>;
  }

  const hasPrevious = offset > 0;
  const hasNext = offset + data.limit < data.total;
  const rangeStart = data.total === 0 ? 0 : offset + 1;
  const rangeEnd = Math.min(offset + data.limit, data.total);

  return (
    <div>
      <div className={styles.filters}>
        <label>
          Mindeststufe{" "}
          <select value={minStufeParam ?? ""} onChange={(event) => updateParam("min_stufe", event.target.value)}>
            <option value="">Alle</option>
            <option value="1">1</option>
            <option value="2">2</option>
            <option value="3">3</option>
          </select>
        </label>
        <label>
          <input
            type="checkbox"
            aria-label="Nur auffällige"
            checked={nurAuffaellige}
            onChange={(event) => updateParam("nur_auffaellige", event.target.checked ? "true" : "")}
          />{" "}
          Nur auffällige
        </label>
      </div>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Name</th>
            <th>Klasse</th>
            <th>Zählerstand</th>
            <th>Benachrichtigt</th>
          </tr>
        </thead>
        <tbody>
          {data.items.map((student) => (
            <tr key={student.id} data-highlighted={student.ohne_massnahme_seit_benachrichtigung}>
              <td>
                <Link to={`/schueler/${student.id}`}>
                  {student.nachname}, {student.vorname}
                </Link>
              </td>
              <td>{student.klasse?.name ?? "—"}</td>
              <td>
                <div className={styles.badges}>
                  {Object.entries(student.zaehlerstand).map(([typ, stand]) => (
                    <StatusBadge
                      key={typ}
                      label={`${ZAEHLERSTAND_LABEL[typ] ?? typ}: ${stand.erreichte_stufe_nr ?? "–"}`}
                      tone={stufeToTone(stand.erreichte_stufe_nr)}
                    />
                  ))}
                </div>
              </td>
              <td>
                <NotificationFlyout benachrichtigung={student.letzte_benachrichtigung} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className={styles.pagination}>
        <button type="button" disabled={!hasPrevious} onClick={() => goToOffset(Math.max(0, offset - data.limit))}>
          Zurück
        </button>
        <span>
          {rangeStart}–{rangeEnd} von {data.total}
        </span>
        <button type="button" disabled={!hasNext} onClick={() => goToOffset(offset + data.limit)}>
          Weiter
        </button>
      </div>
    </div>
  );
}
```

Beachte: `STUDENT_LIST_LIMIT` wird hier nicht importiert — die Pagination rechnet mit `data.limit` aus der Response; die Konstante aus Task 3 bleibt trotzdem exportiert, falls ein späterer Plan einen Default vor dem ersten Request braucht.

- [ ] **Step 4: Test ausführen, Erfolg prüfen**

Run: `cd frontend && npx vitest run src/pages/StudentList/StudentList.test.tsx`
Expected: alle Tests PASS. Falls der Zeilen-Test über `getByRole("row", ...)` den zugänglichen Namen nicht wie erwartet zusammensetzt, stattdessen `container.querySelector('tr[data-highlighted="true"]')` verwenden (RTL importiert `render` bereits mit `container`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/StudentList/
git commit -m "feat: add StudentList page with filters, badges, and pagination"
```

---

## Task 8: Frontend — `FehlzeitenTable` und `KlassenbuchTable`

**Files:**
- Create: `frontend/src/components/StudentDetail/FehlzeitenTable.tsx`
- Create: `frontend/src/components/StudentDetail/FehlzeitenTable.test.tsx`
- Create: `frontend/src/components/StudentDetail/KlassenbuchTable.tsx`
- Create: `frontend/src/components/StudentDetail/KlassenbuchTable.test.tsx`
- Create: `frontend/src/components/StudentDetail/StudentDetail.module.css` (gemeinsames Stylesheet für alle Komponenten in diesem Verzeichnis)

**Interfaces:**
- Consumes: Typen `Fehlzeit`, `ExcuseStatusCatalogEntry`, `KlassenbuchEintrag`, `ClassregCategoryCatalogEntry` (Task 3).
- Produces: `FehlzeitenTable({ fehlzeiten, excuseStatuses }: { fehlzeiten: Fehlzeit[]; excuseStatuses: ExcuseStatusCatalogEntry[] })`, `KlassenbuchTable({ eintraege, classregCategories }: { eintraege: KlassenbuchEintrag[]; classregCategories: ClassregCategoryCatalogEntry[] })`.

- [ ] **Step 1: Tests schreiben**

Erstelle `frontend/src/components/StudentDetail/FehlzeitenTable.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FehlzeitenTable } from "./FehlzeitenTable";

describe("FehlzeitenTable", () => {
  it("resolves excuse_status_id to its long_name", () => {
    render(
      <FehlzeitenTable
        fehlzeiten={[
          {
            id: 1,
            typ: "verspaetung",
            datum: "2026-02-01",
            start_zeit: 1,
            end_zeit: 1,
            fach: "Mathe",
            excuse_status_id: 5,
            grund_text: null,
          },
        ]}
        excuseStatuses={[{ id: 5, name: "E", long_name: "Entschuldigt" }]}
      />,
    );

    expect(screen.getByText("Entschuldigt")).toBeInTheDocument();
    expect(screen.getByText("Mathe")).toBeInTheDocument();
  });

  it("shows a dash when excuse_status_id is null", () => {
    render(
      <FehlzeitenTable
        fehlzeiten={[
          {
            id: 1,
            typ: "verspaetung",
            datum: "2026-02-01",
            start_zeit: 1,
            end_zeit: 1,
            fach: null,
            excuse_status_id: null,
            grund_text: null,
          },
        ]}
        excuseStatuses={[]}
      />,
    );

    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});
```

Erstelle `frontend/src/components/StudentDetail/KlassenbuchTable.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { KlassenbuchTable } from "./KlassenbuchTable";

describe("KlassenbuchTable", () => {
  it("resolves kategorie_id to its long_name", () => {
    render(
      <KlassenbuchTable
        eintraege={[{ id: 1, kategorie_id: 3, datum: "2026-02-01", text: "Gestört", lesson_id: 1 }]}
        classregCategories={[{ id: 3, name: "LSU", long_name: "Lehrstoffunterbrechung" }]}
      />,
    );

    expect(screen.getByText("Lehrstoffunterbrechung")).toBeInTheDocument();
    expect(screen.getByText("Gestört")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Tests ausführen, Fehlschlag prüfen**

Run: `cd frontend && npx vitest run src/components/StudentDetail/FehlzeitenTable.test.tsx src/components/StudentDetail/KlassenbuchTable.test.tsx`
Expected: FAIL (Module existieren nicht).

- [ ] **Step 3: Implementierung**

Erstelle `frontend/src/components/StudentDetail/StudentDetail.module.css`:

```css
.section {
  padding: 1rem 0;
  border-bottom: 1px solid #eee;
}

.table {
  width: 100%;
  border-collapse: collapse;
}

.table th,
.table td {
  text-align: left;
  padding: 0.35rem 0.6rem;
  border-bottom: 1px solid #eee;
}

.form {
  display: flex;
  gap: 0.75rem;
  align-items: flex-end;
  flex-wrap: wrap;
  padding-top: 0.75rem;
}

.form label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.85rem;
}

.formError {
  color: #991b1b;
  font-size: 0.85rem;
}
```

Erstelle `frontend/src/components/StudentDetail/FehlzeitenTable.tsx`:

```tsx
import type { ExcuseStatusCatalogEntry, Fehlzeit } from "../../api/types";
import styles from "./StudentDetail.module.css";

interface FehlzeitenTableProps {
  fehlzeiten: Fehlzeit[];
  excuseStatuses: ExcuseStatusCatalogEntry[];
}

export function FehlzeitenTable({ fehlzeiten, excuseStatuses }: FehlzeitenTableProps) {
  const statusMap = new Map(excuseStatuses.map((status) => [status.id, status.long_name ?? status.name]));

  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th>Datum</th>
          <th>Typ</th>
          <th>Zeit</th>
          <th>Fach</th>
          <th>Entschuldigungsstatus</th>
          <th>Grund</th>
        </tr>
      </thead>
      <tbody>
        {fehlzeiten.map((fehlzeit) => (
          <tr key={fehlzeit.id}>
            <td>{fehlzeit.datum}</td>
            <td>{fehlzeit.typ}</td>
            <td>
              {fehlzeit.start_zeit}–{fehlzeit.end_zeit}
            </td>
            <td>{fehlzeit.fach ?? "—"}</td>
            <td>{fehlzeit.excuse_status_id !== null ? statusMap.get(fehlzeit.excuse_status_id) ?? "—" : "—"}</td>
            <td>{fehlzeit.grund_text ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

Erstelle `frontend/src/components/StudentDetail/KlassenbuchTable.tsx`:

```tsx
import type { ClassregCategoryCatalogEntry, KlassenbuchEintrag } from "../../api/types";
import styles from "./StudentDetail.module.css";

interface KlassenbuchTableProps {
  eintraege: KlassenbuchEintrag[];
  classregCategories: ClassregCategoryCatalogEntry[];
}

export function KlassenbuchTable({ eintraege, classregCategories }: KlassenbuchTableProps) {
  const kategorieMap = new Map(
    classregCategories.map((kategorie) => [kategorie.id, kategorie.long_name ?? kategorie.name]),
  );

  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th>Datum</th>
          <th>Kategorie</th>
          <th>Text</th>
        </tr>
      </thead>
      <tbody>
        {eintraege.map((eintrag) => (
          <tr key={eintrag.id}>
            <td>{eintrag.datum}</td>
            <td>{kategorieMap.get(eintrag.kategorie_id) ?? "—"}</td>
            <td>{eintrag.text ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 4: Tests ausführen, Erfolg prüfen**

Run: `cd frontend && npx vitest run src/components/StudentDetail/FehlzeitenTable.test.tsx src/components/StudentDetail/KlassenbuchTable.test.tsx`
Expected: alle Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/StudentDetail/FehlzeitenTable.tsx frontend/src/components/StudentDetail/FehlzeitenTable.test.tsx frontend/src/components/StudentDetail/KlassenbuchTable.tsx frontend/src/components/StudentDetail/KlassenbuchTable.test.tsx frontend/src/components/StudentDetail/StudentDetail.module.css
git commit -m "feat: add FehlzeitenTable and KlassenbuchTable with catalog name resolution"
```

---

## Task 9: Frontend — `MassnahmenSection` (Historie + Formular)

**Files:**
- Create: `frontend/src/components/StudentDetail/MassnahmenSection.tsx`
- Create: `frontend/src/components/StudentDetail/MassnahmenSection.test.tsx`

**Interfaces:**
- Consumes: `useCreateMeasure` (Task 4), Typen `Massnahme`, `MassnahmenTyp` (Task 3).
- Produces: `MassnahmenSection({ studentId, massnahmen, massnahmenTypen }: { studentId: number; massnahmen: Massnahme[]; massnahmenTypen: MassnahmenTyp[] })`.

- [ ] **Step 1: Test schreiben**

Erstelle `frontend/src/components/StudentDetail/MassnahmenSection.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useCreateMeasure } from "../../api/hooks/useCreateMeasure";
import { MassnahmenSection } from "./MassnahmenSection";

vi.mock("../../api/hooks/useCreateMeasure");

const mockUseCreateMeasure = vi.mocked(useCreateMeasure);

describe("MassnahmenSection", () => {
  it("renders the existing Massnahmen history", () => {
    mockUseCreateMeasure.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    render(
      <MassnahmenSection
        studentId={7}
        massnahmen={[
          {
            id: 1,
            massnahmen_typ_id: 2,
            massnahmen_typ_name: "Gespräch",
            datum: "2026-02-01",
            notiz: "Elterngespräch geführt",
            erfasst_von_nutzer_id: 1,
            erfasst_von_name: "A. Beispiel",
          },
        ]}
        massnahmenTypen={[{ id: 2, name: "Gespräch" }]}
      />,
    );

    expect(screen.getByText("Gespräch")).toBeInTheDocument();
    expect(screen.getByText("A. Beispiel")).toBeInTheDocument();
  });

  it("submits the form with the selected type, date and note", async () => {
    const mutate = vi.fn();
    mockUseCreateMeasure.mockReturnValue({
      mutate,
      isPending: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    render(<MassnahmenSection studentId={7} massnahmen={[]} massnahmenTypen={[{ id: 2, name: "Gespräch" }]} />);

    fireEvent.change(screen.getByLabelText("Typ"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Datum"), { target: { value: "2026-07-28" } });
    fireEvent.change(screen.getByLabelText("Notiz"), { target: { value: "Testnotiz" } });
    fireEvent.click(screen.getByRole("button", { name: "Maßnahme erfassen" }));

    await waitFor(() =>
      expect(mutate).toHaveBeenCalledWith({ massnahmen_typ_id: 2, datum: "2026-07-28", notiz: "Testnotiz" }),
    );
  });

  it("disables the submit button while the mutation is pending", () => {
    mockUseCreateMeasure.mockReturnValue({
      mutate: vi.fn(),
      isPending: true,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    render(<MassnahmenSection studentId={7} massnahmen={[]} massnahmenTypen={[{ id: 2, name: "Gespräch" }]} />);

    expect(screen.getByRole("button", { name: "Maßnahme erfassen" })).toBeDisabled();
  });
});
```

- [ ] **Step 2: Test ausführen, Fehlschlag prüfen**

Run: `cd frontend && npx vitest run src/components/StudentDetail/MassnahmenSection.test.tsx`
Expected: FAIL (Modul existiert nicht).

- [ ] **Step 3: Implementierung**

Erstelle `frontend/src/components/StudentDetail/MassnahmenSection.tsx`:

```tsx
import { useState } from "react";
import { useCreateMeasure } from "../../api/hooks/useCreateMeasure";
import type { Massnahme, MassnahmenTyp } from "../../api/types";
import styles from "./StudentDetail.module.css";

interface MassnahmenSectionProps {
  studentId: number;
  massnahmen: Massnahme[];
  massnahmenTypen: MassnahmenTyp[];
}

export function MassnahmenSection({ studentId, massnahmen, massnahmenTypen }: MassnahmenSectionProps) {
  const { mutate, isPending, error } = useCreateMeasure(studentId);
  const [typId, setTypId] = useState(massnahmenTypen[0]?.id ?? 0);
  const [datum, setDatum] = useState("");
  const [notiz, setNotiz] = useState("");

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    mutate(
      { massnahmen_typ_id: typId, datum, notiz: notiz || null },
      {
        onSuccess: () => {
          setDatum("");
          setNotiz("");
        },
      },
    );
  }

  return (
    <section className={styles.section}>
      <h3>Maßnahmen</h3>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Datum</th>
            <th>Typ</th>
            <th>Notiz</th>
            <th>Erfasst von</th>
          </tr>
        </thead>
        <tbody>
          {massnahmen.map((massnahme) => (
            <tr key={massnahme.id}>
              <td>{massnahme.datum}</td>
              <td>{massnahme.massnahmen_typ_name}</td>
              <td>{massnahme.notiz ?? "—"}</td>
              <td>{massnahme.erfasst_von_name}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <form className={styles.form} onSubmit={handleSubmit}>
        <label>
          Typ
          <select
            aria-label="Typ"
            value={typId}
            onChange={(event) => setTypId(Number(event.target.value))}
          >
            {massnahmenTypen.map((typ) => (
              <option key={typ.id} value={typ.id}>
                {typ.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Datum
          <input aria-label="Datum" type="date" value={datum} onChange={(event) => setDatum(event.target.value)} required />
        </label>
        <label>
          Notiz
          <textarea aria-label="Notiz" value={notiz} onChange={(event) => setNotiz(event.target.value)} />
        </label>
        <button type="submit" disabled={isPending}>
          Maßnahme erfassen
        </button>
        {error && <p className={styles.formError}>Fehler beim Erfassen der Maßnahme.</p>}
      </form>
    </section>
  );
}
```

- [ ] **Step 4: Tests ausführen, Erfolg prüfen**

Run: `cd frontend && npx vitest run src/components/StudentDetail/MassnahmenSection.test.tsx`
Expected: alle Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/StudentDetail/MassnahmenSection.tsx frontend/src/components/StudentDetail/MassnahmenSection.test.tsx
git commit -m "feat: add MassnahmenSection with history table and create form"
```

---

## Task 10: Frontend — `AusnahmenSection` (Liste, Formular, Aufheben)

**Files:**
- Create: `frontend/src/components/StudentDetail/AusnahmenSection.tsx`
- Create: `frontend/src/components/StudentDetail/AusnahmenSection.test.tsx`

**Interfaces:**
- Consumes: `useCreateExemption`, `useRevokeExemption` (Task 4), Typ `Ausnahme` (Task 3).
- Produces: `AusnahmenSection({ studentId, ausnahmen }: { studentId: number; ausnahmen: Ausnahme[] })`.

- [ ] **Step 1: Test schreiben**

Erstelle `frontend/src/components/StudentDetail/AusnahmenSection.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useCreateExemption } from "../../api/hooks/useCreateExemption";
import { useRevokeExemption } from "../../api/hooks/useRevokeExemption";
import { AusnahmenSection } from "./AusnahmenSection";

vi.mock("../../api/hooks/useCreateExemption");
vi.mock("../../api/hooks/useRevokeExemption");

const mockUseCreateExemption = vi.mocked(useCreateExemption);
const mockUseRevokeExemption = vi.mocked(useRevokeExemption);

describe("AusnahmenSection", () => {
  it("renders active and inactive Ausnahmen and offers an Aufheben button only for active ones", () => {
    mockUseCreateExemption.mockReturnValue({ mutate: vi.fn(), isPending: false, error: null } as any); // eslint-disable-line @typescript-eslint/no-explicit-any
    mockUseRevokeExemption.mockReturnValue({ mutate: vi.fn(), isPending: false } as any); // eslint-disable-line @typescript-eslint/no-explicit-any

    render(
      <AusnahmenSection
        studentId={7}
        ausnahmen={[
          { id: 1, kategorie: "fehlzeiten", grund: "Attest", gueltig_bis: null, aktiv: true },
          { id: 2, kategorie: "klassenbuch", grund: "Alt", gueltig_bis: "2026-01-01", aktiv: false },
        ]}
      />,
    );

    expect(screen.getByText("Attest")).toBeInTheDocument();
    expect(screen.getByText("Alt")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Aufheben" })).toHaveLength(1);
  });

  it("calls revoke mutation when Aufheben is clicked", () => {
    const revokeMutate = vi.fn();
    mockUseCreateExemption.mockReturnValue({ mutate: vi.fn(), isPending: false, error: null } as any); // eslint-disable-line @typescript-eslint/no-explicit-any
    mockUseRevokeExemption.mockReturnValue({ mutate: revokeMutate, isPending: false } as any); // eslint-disable-line @typescript-eslint/no-explicit-any

    render(
      <AusnahmenSection
        studentId={7}
        ausnahmen={[{ id: 1, kategorie: "fehlzeiten", grund: "Attest", gueltig_bis: null, aktiv: true }]}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Aufheben" }));
    expect(revokeMutate).toHaveBeenCalledWith(1);
  });

  it("submits the create form with the chosen kategorie, grund and gueltig_bis", async () => {
    const createMutate = vi.fn();
    mockUseCreateExemption.mockReturnValue({ mutate: createMutate, isPending: false, error: null } as any); // eslint-disable-line @typescript-eslint/no-explicit-any
    mockUseRevokeExemption.mockReturnValue({ mutate: vi.fn(), isPending: false } as any); // eslint-disable-line @typescript-eslint/no-explicit-any

    render(<AusnahmenSection studentId={7} ausnahmen={[]} />);

    fireEvent.click(screen.getByLabelText("Klassenbuch"));
    fireEvent.change(screen.getByLabelText("Grund"), { target: { value: "Attest" } });
    fireEvent.change(screen.getByLabelText("Gültig bis"), { target: { value: "2026-08-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Ausnahme setzen" }));

    await waitFor(() =>
      expect(createMutate).toHaveBeenCalledWith({ kategorie: "klassenbuch", grund: "Attest", gueltig_bis: "2026-08-01" }),
    );
  });
});
```

- [ ] **Step 2: Test ausführen, Fehlschlag prüfen**

Run: `cd frontend && npx vitest run src/components/StudentDetail/AusnahmenSection.test.tsx`
Expected: FAIL (Modul existiert nicht).

- [ ] **Step 3: Implementierung**

Erstelle `frontend/src/components/StudentDetail/AusnahmenSection.tsx`:

```tsx
import { useState } from "react";
import { useCreateExemption } from "../../api/hooks/useCreateExemption";
import { useRevokeExemption } from "../../api/hooks/useRevokeExemption";
import type { Ausnahme } from "../../api/types";
import styles from "./StudentDetail.module.css";

interface AusnahmenSectionProps {
  studentId: number;
  ausnahmen: Ausnahme[];
}

export function AusnahmenSection({ studentId, ausnahmen }: AusnahmenSectionProps) {
  const { mutate: createMutate, isPending: isCreating, error } = useCreateExemption(studentId);
  const { mutate: revokeMutate } = useRevokeExemption(studentId);
  const [kategorie, setKategorie] = useState<"fehlzeiten" | "klassenbuch">("fehlzeiten");
  const [grund, setGrund] = useState("");
  const [gueltigBis, setGueltigBis] = useState("");

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    createMutate(
      { kategorie, grund, gueltig_bis: gueltigBis || null },
      {
        onSuccess: () => {
          setGrund("");
          setGueltigBis("");
        },
      },
    );
  }

  return (
    <section className={styles.section}>
      <h3>Ausnahmen</h3>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Kategorie</th>
            <th>Grund</th>
            <th>Gültig bis</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {ausnahmen.map((ausnahme) => (
            <tr key={ausnahme.id}>
              <td>{ausnahme.kategorie}</td>
              <td>{ausnahme.grund}</td>
              <td>{ausnahme.gueltig_bis ?? "unbefristet"}</td>
              <td>{ausnahme.aktiv ? "aktiv" : "aufgehoben"}</td>
              <td>
                {ausnahme.aktiv && (
                  <button type="button" onClick={() => revokeMutate(ausnahme.id)}>
                    Aufheben
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <form className={styles.form} onSubmit={handleSubmit}>
        <label>
          <input
            type="radio"
            name="kategorie"
            value="fehlzeiten"
            checked={kategorie === "fehlzeiten"}
            onChange={() => setKategorie("fehlzeiten")}
          />{" "}
          Fehlzeiten
        </label>
        <label>
          <input
            type="radio"
            name="kategorie"
            value="klassenbuch"
            checked={kategorie === "klassenbuch"}
            onChange={() => setKategorie("klassenbuch")}
          />{" "}
          Klassenbuch
        </label>
        <label>
          Grund
          <input aria-label="Grund" type="text" value={grund} onChange={(event) => setGrund(event.target.value)} required />
        </label>
        <label>
          Gültig bis
          <input
            aria-label="Gültig bis"
            type="date"
            value={gueltigBis}
            onChange={(event) => setGueltigBis(event.target.value)}
          />
        </label>
        <button type="submit" disabled={isCreating}>
          Ausnahme setzen
        </button>
        {error && <p className={styles.formError}>Fehler beim Setzen der Ausnahme.</p>}
      </form>
    </section>
  );
}
```

- [ ] **Step 4: Tests ausführen, Erfolg prüfen**

Run: `cd frontend && npx vitest run src/components/StudentDetail/AusnahmenSection.test.tsx`
Expected: alle Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/StudentDetail/AusnahmenSection.tsx frontend/src/components/StudentDetail/AusnahmenSection.test.tsx
git commit -m "feat: add AusnahmenSection with list, create form and revoke button"
```

---

## Task 11: Frontend — `BenachrichtigungenTable`

**Files:**
- Create: `frontend/src/components/StudentDetail/BenachrichtigungenTable.tsx`
- Create: `frontend/src/components/StudentDetail/BenachrichtigungenTable.test.tsx`

**Interfaces:**
- Consumes: Typ `Benachrichtigung` (Task 3).
- Produces: `BenachrichtigungenTable({ benachrichtigungen }: { benachrichtigungen: Benachrichtigung[] })`.

- [ ] **Step 1: Test schreiben**

Erstelle `frontend/src/components/StudentDetail/BenachrichtigungenTable.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BenachrichtigungenTable } from "./BenachrichtigungenTable";

describe("BenachrichtigungenTable", () => {
  it("lists recipients for a sent notification", () => {
    render(
      <BenachrichtigungenTable
        benachrichtigungen={[
          {
            id: 1,
            regel_id: 1,
            typ: "fehlzeiten",
            stufe_nr: 1,
            gesendet_am: "2026-02-01T00:00:00Z",
            empfaenger: [{ rolle: "klassenlehrkraft", name: "A. Beispiel" }],
            status: "gesendet",
          },
        ]}
      />,
    );

    expect(screen.getByText("fehlzeiten")).toBeInTheDocument();
    expect(screen.getByText("klassenlehrkraft: A. Beispiel")).toBeInTheDocument();
  });

  it("shows a status text when there are no recipients", () => {
    render(
      <BenachrichtigungenTable
        benachrichtigungen={[
          {
            id: 1,
            regel_id: 1,
            typ: "fehlzeiten",
            stufe_nr: 1,
            gesendet_am: "2026-02-01T00:00:00Z",
            empfaenger: [],
            status: "kein_empfaenger",
          },
        ]}
      />,
    );

    expect(screen.getByText("Kein Empfänger ermittelbar")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Test ausführen, Fehlschlag prüfen**

Run: `cd frontend && npx vitest run src/components/StudentDetail/BenachrichtigungenTable.test.tsx`
Expected: FAIL (Modul existiert nicht).

- [ ] **Step 3: Implementierung**

Erstelle `frontend/src/components/StudentDetail/BenachrichtigungenTable.tsx`:

```tsx
import type { Benachrichtigung } from "../../api/types";
import styles from "./StudentDetail.module.css";

interface BenachrichtigungenTableProps {
  benachrichtigungen: Benachrichtigung[];
}

const STATUS_TEXT: Record<string, string> = {
  kein_empfaenger: "Kein Empfänger ermittelbar",
  initial_import: "Aus initialem Datenimport übernommen",
};

export function BenachrichtigungenTable({ benachrichtigungen }: BenachrichtigungenTableProps) {
  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th>Zeitpunkt</th>
          <th>Regel</th>
          <th>Stufe</th>
          <th>Empfänger</th>
        </tr>
      </thead>
      <tbody>
        {benachrichtigungen.map((benachrichtigung) => (
          <tr key={benachrichtigung.id}>
            <td>{benachrichtigung.gesendet_am}</td>
            <td>{benachrichtigung.typ ?? "—"}</td>
            <td>{benachrichtigung.stufe_nr}</td>
            <td>
              {benachrichtigung.empfaenger.length > 0 ? (
                <ul>
                  {benachrichtigung.empfaenger.map((empfaenger, index) => (
                    <li key={index}>
                      {empfaenger.name ? `${empfaenger.rolle}: ${empfaenger.name}` : empfaenger.rolle}
                    </li>
                  ))}
                </ul>
              ) : (
                STATUS_TEXT[benachrichtigung.status] ?? benachrichtigung.status
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 4: Tests ausführen, Erfolg prüfen**

Run: `cd frontend && npx vitest run src/components/StudentDetail/BenachrichtigungenTable.test.tsx`
Expected: alle Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/StudentDetail/BenachrichtigungenTable.tsx frontend/src/components/StudentDetail/BenachrichtigungenTable.test.tsx
git commit -m "feat: add BenachrichtigungenTable component"
```

---

## Task 12: Frontend — `StudentDetail`-Seite

**Files:**
- Create: `frontend/src/pages/StudentDetail/StudentDetail.tsx`
- Create: `frontend/src/pages/StudentDetail/StudentDetail.test.tsx`

**Interfaces:**
- Consumes: `useStudentDetail` (Task 3), `useStudentCatalog` (Task 3), `StatusBadge`/`stufeToTone` (Task 5), `FehlzeitenTable`/`KlassenbuchTable` (Task 8), `MassnahmenSection` (Task 9), `AusnahmenSection` (Task 10), `BenachrichtigungenTable` (Task 11).
- Produces: `StudentDetail` (React-Komponente ohne Props, liest `id` über `useParams<{ id: string }>()`).

- [ ] **Step 1: Test schreiben**

Erstelle `frontend/src/pages/StudentDetail/StudentDetail.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useStudentCatalog } from "../../api/hooks/useStudentCatalog";
import { useStudentDetail } from "../../api/hooks/useStudentDetail";
import { StudentDetail } from "./StudentDetail";

vi.mock("../../api/hooks/useStudentDetail");
vi.mock("../../api/hooks/useStudentCatalog");
vi.mock("../../api/hooks/useCreateMeasure", () => ({
  useCreateMeasure: () => ({ mutate: vi.fn(), isPending: false, error: null }),
}));
vi.mock("../../api/hooks/useCreateExemption", () => ({
  useCreateExemption: () => ({ mutate: vi.fn(), isPending: false, error: null }),
}));
vi.mock("../../api/hooks/useRevokeExemption", () => ({
  useRevokeExemption: () => ({ mutate: vi.fn(), isPending: false }),
}));

const mockUseStudentDetail = vi.mocked(useStudentDetail);
const mockUseStudentCatalog = vi.mocked(useStudentCatalog);

const CATALOG = { massnahmen_typen: [{ id: 1, name: "Gespräch" }], excuse_statuses: [], classreg_categories: [] };

const DETAIL = {
  id: 7,
  vorname: "Max",
  nachname: "Muster",
  klasse: { id: 1, name: "10a" },
  zaehlerstand: {
    fehlzeiten: { aktueller_stand: 4, erreichte_stufe_nr: 1 },
    klassenbuch: { aktueller_stand: 0, erreichte_stufe_nr: null },
  },
  fehlzeiten: [],
  klassenbuch: [],
  massnahmen: [],
  ausnahmen: [],
  benachrichtigungen: [],
};

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={["/schueler/7"]}>
      <Routes>
        <Route path="/schueler/:id" element={<StudentDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("StudentDetail", () => {
  it("renders the student header and all sections", () => {
    mockUseStudentDetail.mockReturnValue({ data: DETAIL, isLoading: false, isError: false } as any); // eslint-disable-line @typescript-eslint/no-explicit-any
    mockUseStudentCatalog.mockReturnValue({ data: CATALOG, isLoading: false, isError: false } as any); // eslint-disable-line @typescript-eslint/no-explicit-any

    renderDetail();

    expect(screen.getByText("Muster, Max")).toBeInTheDocument();
    expect(screen.getByText("10a")).toBeInTheDocument();
    expect(screen.getByText("Maßnahmen")).toBeInTheDocument();
    expect(screen.getByText("Ausnahmen")).toBeInTheDocument();
  });

  it("shows an error message when the detail request fails", () => {
    mockUseStudentDetail.mockReturnValue({ data: undefined, isLoading: false, isError: true } as any); // eslint-disable-line @typescript-eslint/no-explicit-any
    mockUseStudentCatalog.mockReturnValue({ data: CATALOG, isLoading: false, isError: false } as any); // eslint-disable-line @typescript-eslint/no-explicit-any

    renderDetail();

    expect(screen.getByText("Fehler beim Laden des Schülers.")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Test ausführen, Fehlschlag prüfen**

Run: `cd frontend && npx vitest run src/pages/StudentDetail/StudentDetail.test.tsx`
Expected: FAIL (Modul existiert nicht).

- [ ] **Step 3: Implementierung**

Erstelle `frontend/src/pages/StudentDetail/StudentDetail.tsx`:

```tsx
import { useParams } from "react-router-dom";
import { useStudentCatalog } from "../../api/hooks/useStudentCatalog";
import { useStudentDetail } from "../../api/hooks/useStudentDetail";
import { AusnahmenSection } from "../../components/StudentDetail/AusnahmenSection";
import { BenachrichtigungenTable } from "../../components/StudentDetail/BenachrichtigungenTable";
import { FehlzeitenTable } from "../../components/StudentDetail/FehlzeitenTable";
import { KlassenbuchTable } from "../../components/StudentDetail/KlassenbuchTable";
import { MassnahmenSection } from "../../components/StudentDetail/MassnahmenSection";
import styles from "../../components/StudentDetail/StudentDetail.module.css";
import { StatusBadge, stufeToTone } from "../../components/StatusBadge/StatusBadge";

const ZAEHLERSTAND_LABEL: Record<string, string> = {
  fehlzeiten: "Fehlzeiten",
  klassenbuch: "Klassenbuch",
};

export function StudentDetail() {
  const { id } = useParams<{ id: string }>();
  const studentId = Number(id);
  const { data: student, isLoading, isError } = useStudentDetail(studentId);
  const { data: catalog } = useStudentCatalog();

  if (isLoading) {
    return <p>Lädt Schülerdaten…</p>;
  }
  if (isError || !student) {
    return <p>Fehler beim Laden des Schülers.</p>;
  }

  return (
    <div>
      <section className={styles.section}>
        <h2>
          {student.nachname}, {student.vorname}
        </h2>
        <p>{student.klasse?.name ?? "—"}</p>
        <div>
          {Object.entries(student.zaehlerstand).map(([typ, stand]) => (
            <StatusBadge
              key={typ}
              label={`${ZAEHLERSTAND_LABEL[typ] ?? typ}: ${stand.erreichte_stufe_nr ?? "–"}`}
              tone={stufeToTone(stand.erreichte_stufe_nr)}
            />
          ))}
        </div>
      </section>
      <section className={styles.section}>
        <h3>Fehlzeiten</h3>
        <FehlzeitenTable fehlzeiten={student.fehlzeiten} excuseStatuses={catalog?.excuse_statuses ?? []} />
      </section>
      <section className={styles.section}>
        <h3>Klassenbuch</h3>
        <KlassenbuchTable eintraege={student.klassenbuch} classregCategories={catalog?.classreg_categories ?? []} />
      </section>
      <MassnahmenSection
        studentId={studentId}
        massnahmen={student.massnahmen}
        massnahmenTypen={catalog?.massnahmen_typen ?? []}
      />
      <AusnahmenSection studentId={studentId} ausnahmen={student.ausnahmen} />
      <section className={styles.section}>
        <h3>Benachrichtigungen</h3>
        <BenachrichtigungenTable benachrichtigungen={student.benachrichtigungen} />
      </section>
    </div>
  );
}
```

- [ ] **Step 4: Tests ausführen, Erfolg prüfen**

Run: `cd frontend && npx vitest run src/pages/StudentDetail/StudentDetail.test.tsx`
Expected: alle Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/StudentDetail/
git commit -m "feat: add StudentDetail page composing all detail sections"
```

---

## Task 13: Frontend — Routing & Navigation-Tabs

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`
- Modify: `frontend/src/components/Navigation/Navigation.tsx`
- Modify: `frontend/src/components/Navigation/Navigation.module.css`
- Modify: `frontend/src/components/Navigation/Navigation.test.tsx`

**Interfaces:**
- Consumes: `StudentList` (Task 7), `StudentDetail` (Task 12).
- Produces: Routen `/schueler`, `/schueler/:id` in `App.tsx`; `Navigation` rendert zusätzlich zwei Tabs.

- [ ] **Step 1: `App.test.tsx` anpassen**

In `frontend/src/App.test.tsx`: Mocks für `useStudents`, `useStudentDetail`, `useStudentCatalog` ergänzen (analog `useNavOptions`/`useStats`), den bestehenden `"renders the Klasse placeholder route"`-Test durch zwei neue Tests ersetzen:

```tsx
vi.mock("./api/hooks/useStudents");
vi.mock("./api/hooks/useStudentDetail");
vi.mock("./api/hooks/useStudentCatalog");
```

(Imports ergänzen: `import { useStudents } from "./api/hooks/useStudents";`, `import { useStudentDetail } from "./api/hooks/useStudentDetail";`, `import { useStudentCatalog } from "./api/hooks/useStudentCatalog";`, jeweils `vi.mocked(...)`-Konstanten analog den bestehenden.)

`setupMocks()` ergänzen:

```ts
mockUseStudents.mockReturnValue({
  data: { items: [], total: 0, limit: 50, offset: 0 },
  isLoading: false,
  isError: false,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
} as any);
mockUseStudentDetail.mockReturnValue({
  data: {
    id: 1,
    vorname: "Max",
    nachname: "Muster",
    klasse: null,
    zaehlerstand: {},
    fehlzeiten: [],
    klassenbuch: [],
    massnahmen: [],
    ausnahmen: [],
    benachrichtigungen: [],
  },
  isLoading: false,
  isError: false,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
} as any);
mockUseStudentCatalog.mockReturnValue({
  data: { massnahmen_typen: [], excuse_statuses: [], classreg_categories: [] },
  isLoading: false,
  isError: false,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
} as any);
```

`"renders the Klasse placeholder route"`-Test ersetzen durch:

```tsx
it("renders the Schülerliste route", () => {
  setupMocks();
  render(
    <MemoryRouter initialEntries={["/schueler"]}>
      <App />
    </MemoryRouter>,
  );
  expect(screen.getByText("Name")).toBeInTheDocument();
});

it("renders the Schüler-Detail route", () => {
  setupMocks();
  render(
    <MemoryRouter initialEntries={["/schueler/1"]}>
      <App />
    </MemoryRouter>,
  );
  expect(screen.getByText("Muster, Max")).toBeInTheDocument();
});
```

- [ ] **Step 2: `Navigation.test.tsx` um Tab-Erwartung ergänzen**

In `frontend/src/components/Navigation/Navigation.test.tsx` einen neuen Test ergänzen (nutzt das erste, bereits vorhandene `mockUseNavOptions.mockReturnValue`-Setup mit `bereiche: []`, `klassen: [...]`):

```tsx
it("renders navigation tabs that preserve the current search params", () => {
  mockUseNavOptions.mockReturnValue({
    data: { bereiche: [], klassen: [{ id: 1, name: "10a", bereich_id: null }] },
    isLoading: false,
    isError: false,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any);

  renderNavigation(["/?klasse=1"]);

  expect(screen.getByRole("link", { name: "Übersicht" })).toHaveAttribute("href", "/?klasse=1");
  expect(screen.getByRole("link", { name: "Schülerliste" })).toHaveAttribute("href", "/schueler?klasse=1");
});
```

- [ ] **Step 3: Tests ausführen, Fehlschlag prüfen**

Run: `cd frontend && npx vitest run src/App.test.tsx src/components/Navigation/Navigation.test.tsx`
Expected: FAIL (Routen/Tabs existieren noch nicht, `Name`-Text aus `StudentList` bzw. `Muster, Max` aus `StudentDetail` fehlen).

- [ ] **Step 4: `App.tsx` anpassen**

```tsx
import { Outlet, Route, Routes } from "react-router-dom";
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
```

- [ ] **Step 5: `Navigation.tsx` um Tabs erweitern**

In `frontend/src/components/Navigation/Navigation.tsx`: Import `Link, useLocation` zu `react-router-dom`-Import hinzufügen, `useLocation()` innerhalb der Komponente aufrufen, und im JSX vor den Dropdowns folgendes einfügen (innerhalb des bestehenden `<nav className={styles.nav}>`):

```tsx
<div className={styles.tabs}>
  <Link to={{ pathname: "/", search: location.search }} className={location.pathname === "/" ? styles.tabActive : styles.tab}>
    Übersicht
  </Link>
  <Link
    to={{ pathname: "/schueler", search: location.search }}
    className={location.pathname === "/schueler" ? styles.tabActive : styles.tab}
  >
    Schülerliste
  </Link>
</div>
```

(`location` kommt aus `const location = useLocation();`, ergänzt direkt nach der bestehenden `const [searchParams, setSearchParams] = useSearchParams();`-Zeile.)

- [ ] **Step 6: `Navigation.module.css` um Tab-Styles ergänzen**

Ans Dateiende anfügen:

```css
.tabs {
  display: flex;
  gap: 1rem;
}

.tab,
.tabActive {
  text-decoration: none;
  color: inherit;
  padding-bottom: 0.25rem;
}

.tabActive {
  border-bottom: 2px solid #1e40af;
  font-weight: 600;
}
```

- [ ] **Step 7: Tests ausführen, Erfolg prüfen**

Run: `cd frontend && npx vitest run`
Expected: alle Frontend-Tests PASS (kompletter Testlauf, nicht nur die zwei geänderten Dateien — Task 12 hängt z.B. an `student-catalog`-Query-Keys, die hier nicht verändert wurden, aber zur Sicherheit einmal komplett laufen lassen).

- [ ] **Step 8: Kompletten Testlauf und Build prüfen**

Run: `cd frontend && npx vitest run && npx tsc --noEmit && npx vite build`
Expected: Tests PASS, keine TypeScript-Fehler, Build erfolgreich (schreibt nach `wordpress-plugin/absenzdash/assets/spa/`, siehe Plan 9).

- [ ] **Step 9: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/components/Navigation/Navigation.tsx frontend/src/components/Navigation/Navigation.module.css frontend/src/components/Navigation/Navigation.test.tsx
git commit -m "feat: wire up Schülerliste/Schüler-Detail routes and navigation tabs"
```

---

## Nach Abschluss aller Tasks

- [ ] **ROADMAP.md aktualisieren**: neuen Plan unter "Abgeschlossen" eintragen (Verweis auf diese Datei), aus "Geplant" den entsprechenden Punkt entfernen bzw. anpassen (Roadmap-Punkt 1 "WordPress-Plugin (Verbleibende Teile)" bleibt unberührt, der jetzt abgedeckte Teil war noch nicht als eigener Roadmap-Punkt gelistet — als neue Zeile in "Abgeschlossen" ergänzen, analog Plan 9).
- [ ] Commit für die ROADMAP.md-Aktualisierung.

## Self-Review-Notizen (bereits eingearbeitet)

- **Spec-Abdeckung**: Schülerliste (Task 7) mit Filtern/Badges/Flyout/Pagination, Schüler-Detail (Task 12) mit allen fünf Historien-Abschnitten, Maßnahmen-Formular (Task 9), Ausnahmen-Formular+Aufheben (Task 10) — alle SPECS.md-§7-Punkte für diesen Plan abgedeckt. Katalog-Lücke (Task 1) und Routing/Navigation (Task 13) ergänzen die technischen Voraussetzungen.
- **Reihenfolge-Bug vermieden**: Task 1 platziert `/students/catalog` explizit vor `/{schueler_id}`.
- **Typkonsistenz geprüft**: `StudentListParams`/`CreateMeasureInput`/`CreateExemptionInput`-Feldnamen sind in Task 3/4 (Definition) und Task 7/9/10 (Verwendung) identisch; `studentDetailQueryKey` wird in Task 3 definiert und in Task 4/12 unverändert übernommen.
