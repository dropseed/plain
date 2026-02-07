/**
 * Plain React - Client-side runtime for Plain + React integration.
 *
 * Provides SPA navigation, form handling, and component rendering
 * while keeping all routing and data logic on the Python server.
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { createRoot } from "react-dom/client";

// ============================================================================
// Page Context
// ============================================================================

const PageContext = createContext(null);

/**
 * Access the current page data (component, props, url) from any component.
 *
 *   const { props, url, component } = usePage();
 */
export function usePage() {
  const context = useContext(PageContext);
  if (!context) {
    throw new Error("usePage() must be used within a Plain React app");
  }
  return context;
}

// ============================================================================
// Router
// ============================================================================

/**
 * The router handles SPA navigation by intercepting requests and swapping
 * React components on the client side.
 */
export const router = {
  _listeners: new Set(),
  _currentPage: null,
  _resolveComponent: null,

  /**
   * Navigate to a URL, fetching the new page data from the server.
   */
  async visit(url, options = {}) {
    const {
      method = "GET",
      data = null,
      headers = {},
      preserveScroll = false,
      replace = false,
      onBefore,
      onSuccess,
      onError,
      onFinish,
    } = options;

    if (onBefore && onBefore() === false) return;

    // Notify listeners that navigation is starting
    this._emit("start", { url, method });

    try {
      const fetchOptions = {
        method: method.toUpperCase(),
        headers: {
          "X-Plain-React": "true",
          Accept: "application/json",
          ...headers,
        },
        credentials: "same-origin",
      };

      if (data && method.toUpperCase() !== "GET") {
        if (data instanceof FormData) {
          fetchOptions.body = data;
        } else {
          fetchOptions.headers["Content-Type"] = "application/json";
          fetchOptions.body = JSON.stringify(data);
        }
      }

      // For GET requests with data, append to URL as query params
      let fetchUrl = url;
      if (data && method.toUpperCase() === "GET") {
        const params = new URLSearchParams(data);
        fetchUrl = `${url}${url.includes("?") ? "&" : "?"}${params}`;
      }

      const response = await fetch(fetchUrl, fetchOptions);

      // Handle redirects (the browser follows them automatically with fetch,
      // but we need to check if the final response is a React page)
      if (response.redirected) {
        // The browser already followed the redirect. Check if the response
        // is a React JSON response or a full HTML page.
        if (response.headers.get("X-Plain-React") === "true") {
          const pageData = await response.json();
          this._setPage(pageData, { preserveScroll, replace });
          onSuccess?.(pageData);
        } else {
          // Server returned HTML (non-React page). Do a full page visit.
          window.location.href = response.url;
          return;
        }
      } else if (response.ok) {
        const contentType = response.headers.get("Content-Type") || "";
        if (contentType.includes("application/json")) {
          const pageData = await response.json();
          this._setPage(pageData, { preserveScroll, replace });
          onSuccess?.(pageData);
        } else {
          // Non-JSON response, do a full page reload
          window.location.href = url;
          return;
        }
      } else {
        // Error response - try to parse as JSON for validation errors
        const contentType = response.headers.get("Content-Type") || "";
        if (contentType.includes("application/json")) {
          const errorData = await response.json();
          // If it's a page response with errors in props, render it
          if (errorData.component) {
            this._setPage(errorData, { preserveScroll: true, replace: true });
          }
          onError?.(errorData);
        } else {
          onError?.({ status: response.status });
        }
      }
    } catch (error) {
      console.error("Plain React navigation error:", error);
      onError?.({ error: error.message });
    } finally {
      this._emit("finish", { url, method });
      onFinish?.();
    }
  },

  /**
   * Navigate via GET request.
   */
  get(url, data = {}, options = {}) {
    return this.visit(url, { ...options, method: "GET", data });
  },

  /**
   * Navigate via POST request.
   */
  post(url, data = {}, options = {}) {
    return this.visit(url, { ...options, method: "POST", data });
  },

  /**
   * Navigate via PUT request.
   */
  put(url, data = {}, options = {}) {
    return this.visit(url, { ...options, method: "PUT", data });
  },

  /**
   * Navigate via PATCH request.
   */
  patch(url, data = {}, options = {}) {
    return this.visit(url, { ...options, method: "PATCH", data });
  },

  /**
   * Navigate via DELETE request.
   */
  delete(url, options = {}) {
    return this.visit(url, { ...options, method: "DELETE" });
  },

  /**
   * Reload the current page (re-fetch props from server).
   */
  reload(options = {}) {
    if (this._currentPage) {
      return this.visit(this._currentPage.url, {
        ...options,
        preserveScroll: true,
        replace: true,
      });
    }
  },

  // Internal: set the current page and notify subscribers
  _setPage(pageData, { preserveScroll = false, replace = false } = {}) {
    this._currentPage = pageData;

    if (replace) {
      window.history.replaceState(pageData, "", pageData.url);
    } else {
      window.history.pushState(pageData, "", pageData.url);
    }

    if (!preserveScroll) {
      window.scrollTo(0, 0);
    }

    this._emit("navigate", pageData);
  },

  // Internal: emit events to listeners
  _emit(event, data) {
    for (const listener of this._listeners) {
      listener(event, data);
    }
  },

  // Subscribe to router events
  on(callback) {
    this._listeners.add(callback);
    return () => this._listeners.delete(callback);
  },
};

// ============================================================================
// Link Component
// ============================================================================

/**
 * A link component that performs SPA navigation instead of full page loads.
 *
 *   <Link href="/users">Users</Link>
 *   <Link href="/users" method="post" data={{ name: "John" }}>Create</Link>
 *   <Link href="/logout" method="post" as="button">Logout</Link>
 */
export function Link({
  href,
  method = "GET",
  data,
  as: Component = "a",
  preserveScroll = false,
  replace = false,
  headers = {},
  onClick,
  children,
  ...rest
}) {
  const handleClick = useCallback(
    (e) => {
      if (onClick) onClick(e);
      if (e.defaultPrevented) return;

      // Let the browser handle modifier clicks (new tab, etc.)
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;

      e.preventDefault();

      router.visit(href, {
        method,
        data,
        preserveScroll,
        replace,
        headers,
      });
    },
    [href, method, data, preserveScroll, replace, headers, onClick],
  );

  // Only set href for anchor elements
  const props =
    Component === "a"
      ? { href, onClick: handleClick, ...rest }
      : { onClick: handleClick, type: "button", ...rest };

  return React.createElement(Component, props, children);
}

// ============================================================================
// useForm Hook
// ============================================================================

/**
 * Form helper hook for submitting data to the server.
 *
 *   const form = useForm({ name: "", email: "" });
 *
 *   <form onSubmit={(e) => { e.preventDefault(); form.post("/users"); }}>
 *     <input value={form.data.name} onChange={e => form.setData("name", e.target.value)} />
 *     {form.errors.name && <span>{form.errors.name}</span>}
 *     <button disabled={form.processing}>Submit</button>
 *   </form>
 */
export function useForm(initialData = {}) {
  const [data, setDataState] = useState(initialData);
  const [errors, setErrors] = useState({});
  const [processing, setProcessing] = useState(false);
  const [recentlySuccessful, setRecentlySuccessful] = useState(false);
  const initialDataRef = useRef(initialData);
  const recentlySuccessfulTimeoutRef = useRef(null);

  const setData = useCallback((keyOrUpdater, value) => {
    if (typeof keyOrUpdater === "function") {
      setDataState(keyOrUpdater);
    } else if (typeof keyOrUpdater === "string") {
      setDataState((prev) => ({ ...prev, [keyOrUpdater]: value }));
    } else {
      // Object form: setData({ name: "John", email: "..." })
      setDataState(keyOrUpdater);
    }
  }, []);

  const reset = useCallback((...fields) => {
    if (fields.length === 0) {
      setDataState(initialDataRef.current);
    } else {
      setDataState((prev) => {
        const next = { ...prev };
        for (const field of fields) {
          next[field] = initialDataRef.current[field];
        }
        return next;
      });
    }
    setErrors({});
  }, []);

  const clearErrors = useCallback((...fields) => {
    if (fields.length === 0) {
      setErrors({});
    } else {
      setErrors((prev) => {
        const next = { ...prev };
        for (const field of fields) {
          delete next[field];
        }
        return next;
      });
    }
  }, []);

  const submit = useCallback(
    (method, url, options = {}) => {
      setProcessing(true);
      setRecentlySuccessful(false);

      return router.visit(url, {
        method,
        data,
        preserveScroll: true,
        ...options,
        onSuccess: (pageData) => {
          // Check for validation errors in the response props
          if (pageData.props?.errors) {
            setErrors(pageData.props.errors);
          } else {
            setErrors({});
            setRecentlySuccessful(true);
            if (recentlySuccessfulTimeoutRef.current) {
              clearTimeout(recentlySuccessfulTimeoutRef.current);
            }
            recentlySuccessfulTimeoutRef.current = setTimeout(() => {
              setRecentlySuccessful(false);
            }, 2000);
          }
          options.onSuccess?.(pageData);
        },
        onError: (errorData) => {
          if (errorData?.props?.errors) {
            setErrors(errorData.props.errors);
          } else if (
            errorData &&
            typeof errorData === "object" &&
            !errorData.component
          ) {
            // Plain error object (e.g., from API view)
            setErrors(errorData);
          }
          options.onError?.(errorData);
        },
        onFinish: () => {
          setProcessing(false);
          options.onFinish?.();
        },
      });
    },
    [data],
  );

  const isDirty =
    JSON.stringify(data) !== JSON.stringify(initialDataRef.current);

  return {
    data,
    setData,
    errors,
    hasErrors: Object.keys(errors).length > 0,
    processing,
    recentlySuccessful,
    isDirty,
    reset,
    clearErrors,
    submit,
    get: (url, options) => submit("GET", url, options),
    post: (url, options) => submit("POST", url, options),
    put: (url, options) => submit("PUT", url, options),
    patch: (url, options) => submit("PATCH", url, options),
    delete: (url, options) => submit("DELETE", url, options),
  };
}

// ============================================================================
// App Component & Bootstrap
// ============================================================================

function PlainReactApp({ initialPage, resolveComponent }) {
  const [page, setPage] = useState(initialPage);

  useEffect(() => {
    // Listen for SPA navigations
    const unsubscribe = router.on((event, data) => {
      if (event === "navigate") {
        setPage(data);
      }
    });

    // Handle browser back/forward
    const handlePopState = (e) => {
      if (e.state?.component) {
        setPage(e.state);
      }
    };
    window.addEventListener("popstate", handlePopState);

    // Set initial history state
    window.history.replaceState(initialPage, "", initialPage.url);

    return () => {
      unsubscribe();
      window.removeEventListener("popstate", handlePopState);
    };
  }, [initialPage]);

  // Store resolve function and current page on the router
  router._resolveComponent = resolveComponent;
  router._currentPage = page;

  // Resolve the page component
  const pageModule = resolveComponent(page.component);
  const PageComponent = pageModule.default || pageModule;

  // Resolve layout if specified
  let content = React.createElement(PageComponent, page.props);

  if (page.layout) {
    const layoutModule = resolveComponent(page.layout);
    const LayoutComponent = layoutModule.default || layoutModule;
    content = React.createElement(LayoutComponent, {}, content);
  }

  return React.createElement(PageContext.Provider, { value: page }, content);
}

/**
 * Bootstrap the Plain React app.
 *
 *   createPlainApp({
 *     resolve: (name) => {
 *       const pages = import.meta.glob("./pages/*.jsx", { eager: true });
 *       return pages[`./pages/${name}.jsx`];
 *     },
 *   });
 */
export function createPlainApp({ resolve, rootId = "app" } = {}) {
  const el = document.getElementById(rootId);
  if (!el) {
    throw new Error(`Root element #${rootId} not found`);
  }

  const pageDataAttr = el.getAttribute("data-page");
  if (!pageDataAttr) {
    throw new Error("No data-page attribute found on root element");
  }

  const initialPage = JSON.parse(pageDataAttr);

  const app = React.createElement(PlainReactApp, {
    initialPage,
    resolveComponent: resolve,
  });

  createRoot(el).render(app);
}

// ============================================================================
// React Islands - Mount individual components in Jinja2 templates
// ============================================================================

/**
 * Mount React components on all elements with [data-react-component].
 *
 * Used by the {% react %} template tag to embed individual React components
 * inside server-rendered Jinja2 templates.
 *
 *   import { mountIslands } from "./plain-react";
 *
 *   mountIslands({
 *     resolve: (name) => {
 *       const components = import.meta.glob("./components/**\/*.jsx", { eager: true });
 *       return components[`./components/${name}.jsx`];
 *     },
 *   });
 */
export function mountIslands({ resolve } = {}) {
  if (!resolve) {
    throw new Error("mountIslands() requires a resolve function");
  }

  const elements = document.querySelectorAll("[data-react-component]");

  for (const el of elements) {
    const name = el.getAttribute("data-react-component");
    if (!name) continue;

    const propsAttr = el.getAttribute("data-react-props");
    const props = propsAttr ? JSON.parse(propsAttr) : {};

    const mod = resolve(name);
    const Component = mod.default || mod;

    createRoot(el).render(React.createElement(Component, props));
  }
}
