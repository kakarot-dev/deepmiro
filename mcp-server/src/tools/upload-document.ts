// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 kakarot-dev

import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { MirofishClient } from "../client/mirofish-client.js";
import { toMcpError } from "../errors/index.js";

const inputSchema = {
  file_path: z
    .string()
    .describe("Absolute path to the file to upload (PDF, MD, or TXT). Max 10MB."),
};

export function registerUploadDocument(server: McpServer, client: MirofishClient): void {
  server.registerTool(
    "upload_document",
    {
      title: "Upload Document",
      description:
        "Upload a document for use in simulations. Server-side validation and text extraction. " +
        "Returns a document_id to pass to create_simulation. Supports PDF, Markdown, and plain text.",
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
