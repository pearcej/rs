import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({mode}) => {
    let basedir = "/";
    if (mode === "production") {
        basedir = "/assignment/react/";
    } 
    return {
        build: {
            outDir: "../react",
            base: "/assignment/react/",
        },
        server: {
            proxy: {
                "/ns": "http://localhost",

                "/assignment": "http://localhost",
            },
        },
        // base: "/assignment/react/", // this changes the base for dev as well as prod :-(
        // see:  https://vitejs.dev/config/ to conditionalize this
        base: basedir,
        plugins: [react()],
    };
});
