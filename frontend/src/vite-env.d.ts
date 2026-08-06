/// <reference types="vite/client" />

declare module "*.module.css" {
  const classes: { readonly [key: string]: string };
  export default classes;
}

interface ImportMetaEnv {
  // Schaltet das ?a=1-Anonymisierungs-Feature (Schülerliste/-Detail) frei - deaktiviert
  // per Default, siehe frontend/.env.example.
  readonly VITE_ANONYMISIERUNG_AKTIV?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
