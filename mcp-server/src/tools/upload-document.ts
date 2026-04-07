// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 kakarot-dev

import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { MirofishClient } from "../client/mirofish-client.js";
import { toMcpError } from "../errors/index.js";

const inputSchema = {
  file_path: z
    .string()
    .describe("Absolute path to the file to upload. Supported: PDF, MD, TXT. Max 10MB. Rejects binary files and unsupported formats."),
};

export function registerUploadDocument(server: McpServer, client: MirofishClient): void {
  server.registerTool(
    "upload_document",
    {
      title: "Upload Document",
      description:
        "Upload a document for use in simulations. " +
        "LIMITS: Max 10MB, PDF/MD/TXT only. " +
        "The server extracts text server-side (PyMuPDF for PDFs). " +
        "Returns a document_id to pass to create_simulation. " +
        "NOTE: Only works with local file paths (stdio transport). " +
        "For remote/hosted mode, the client skill uploads via HTTP instead.",
      inputSchema,
      annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
    },
    async (args) => {
      try {
        const result = await client.uploadDocument(args.file_path);
        return {
          content: [
            {
              type: "text" as const,
              text: JSON.stringify(
                {
                  document_id: result.document_id,
                  filename: result.filename,
                  text_length: result.text_length,
                  mime_type: result.mime_type,
                  message: `Document uploaded and processed (${result.text_length} characters extracted). Use this document_id with create_simulation.`,
                },
                null,
                2,
              ),
            },
          ],
        };
      } catch (err) {
        throw toMcpError(err);
      }
    },
  );
}
