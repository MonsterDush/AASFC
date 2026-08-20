export {};

declare global {
  interface Window {
    __AXELIO_EARLY_ERRORS__?: Array<Record<string, unknown>>;
    __AXELIO_RELEASE_EARLY_ERROR_LISTENERS__?: () => void;
    AxelioErrorTracking?: Readonly<{
      enabled: boolean;
      captureException?: (error: unknown, context?: unknown) => string;
      captureMessage?: (message: string, context?: unknown) => string;
    }>;
    AxelioPageLoader?: {
      begin: () => () => void;
      finish: (reason?: string) => void;
      readonly pending: number;
      readonly ready: boolean;
    };
  }
}
