// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 kakarot-dev

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { MirofishClient } from "../client/mirofish-client.js";
import { registerCreateSimulation } from "./create-simulation.js";
import { registerSimulationStatus } from "./simulation-status.js";
import { registerGetReport } from "./get-report.js";
import { registerInterviewAgent } from "./interview-agent.js";
import { registerListSimulations } from "./list-simulations.js";
import { registerSearchSimulations } from "./search-simulations.js";
import { registerQuickPredict } from "./quick-predict.js";
import { registerUploadDocument } from "./upload-document.js";
import { registerSimulationData } from "./simulation-data.js";
import { registerCancelSimulation } from "./cancel-simulation.js";

export function registerAllTools(server: McpServer, client: MirofishClient): void {
  registerCreateSimulation(server, client);
  registerSimulationStatus(server, client);
  registerGetReport(server, client);
  registerInterviewAgent(server, client);
  registerListSimulations(server, client);
  registerSearchSimulations(server, client);
  registerQuickPredict(server, client);
  registerUploadDocument(server, client);
  registerSimulationData(server, client);
  registerCancelSimulation(server, client);
}
