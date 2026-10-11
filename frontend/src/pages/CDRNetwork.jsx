import React, { useMemo } from "react";
import "./cdr-network.css";

function getNodeId(node, index) {
  if (typeof node === "string" || typeof node === "number") {
    return String(node);
  }

  return String(
    node?.id ??
    node?.phone_number ??
    node?.number ??
    node?.cid ??
    node?.name ??
    `node-${index}`
  );
}

function getEndpointId(endpoint) {
  if (endpoint && typeof endpoint === "object") {
    return String(
      endpoint.id ??
      endpoint.phone_number ??
      endpoint.number ??
      endpoint.cid ??
      endpoint.name ??
      ""
    );
  }

  return String(endpoint ?? "");
}

function getEdgeEndpoints(edge) {
  return {
    source: getEndpointId(
      edge.source ??
      edge.from ??
      edge.source_id ??
      edge.caller ??
      edge.calling_number
    ),
    target: getEndpointId(
      edge.target ??
      edge.to ??
      edge.target_id ??
      edge.callee ??
      edge.called_number
    ),
  };
}

export default function CDRNetwork({ data, targetNumber }) {
  const nodes = Array.isArray(data?.nodes) ? data.nodes : [];
  const edges = Array.isArray(data?.edges) ? data.edges : [];

  const graph = useMemo(() => {
    const width = 720;
    const height = 420;
    const centerX = width / 2;
    const centerY = height / 2;
    const radius = Math.min(width * 0.38, height * 0.38);

    const positionedNodes = nodes.map((node, index) => {
      const angle =
        (2 * Math.PI * index) / Math.max(nodes.length, 1) -
        Math.PI / 2;

      return {
        raw: node,
        id: getNodeId(node, index),
        x: nodes.length === 1
          ? centerX
          : centerX + radius * Math.cos(angle),
        y: nodes.length === 1
          ? centerY
          : centerY + radius * Math.sin(angle),
      };
    });

    const nodeMap = new Map(
      positionedNodes.map((node) => [node.id, node])
    );

    const positionedEdges = edges
      .map((edge, index) => {
        const endpoints = getEdgeEndpoints(edge);
        const source = nodeMap.get(endpoints.source);
        const target = nodeMap.get(endpoints.target);

        if (!source || !target) return null;

        return {
          ...edge,
          id: `edge-${index}`,
          sourceNode: source,
          targetNode: target,
          count:
            edge.total_interactions ??
            edge.interaction_count ??
            edge.total_calls ??
            edge.weight ??
            null,
        };
      })
      .filter(Boolean);

    return { width, height, positionedNodes, positionedEdges };
  }, [nodes, edges]);

  if (!nodes.length) {
    return (
      <div className="cdr-network-empty">
        No communication-network data is available.
      </div>
    );
  }

  return (
    <section className="cdr-network">
      <div className="cdr-network-heading">
        <div>
          <h3>Communication Network</h3>
          <p>
            Each node represents a contact. Lines represent recorded
            communication links.
          </p>
        </div>

        <div className="cdr-network-stats">
          <span>{nodes.length} nodes</span>
          <span>{edges.length} links</span>
        </div>
      </div>

      <div className="cdr-network-canvas">
        <svg
          viewBox={`0 0 ${graph.width} ${graph.height}`}
          role="img"
          aria-label="Communication network graph"
        >
          {graph.positionedEdges.map((edge) => {
            const { sourceNode, targetNode } = edge;

            return (
              <g key={edge.id}>
                <line
                  x1={sourceNode.x}
                  y1={sourceNode.y}
                  x2={targetNode.x}
                  y2={targetNode.y}
                  className="cdr-network-edge"
                >
                  <title>
                    {sourceNode.id} to {targetNode.id}
                    {edge.count != null
                      ? `: ${edge.count} interactions`
                      : ""}
                  </title>
                </line>

                {edge.count != null && (
                  <text
                    x={(sourceNode.x + targetNode.x) / 2}
                    y={(sourceNode.y + targetNode.y) / 2 - 5}
                    className="cdr-network-edge-label"
                    textAnchor="middle"
                  >
                    {edge.count}
                  </text>
                )}
              </g>
            );
          })}

          {graph.positionedNodes.map((node) => {
            const raw = node.raw;
            const label =
              raw?.name && raw.name !== "unknown"
              ? raw.name
              : raw?.label ||
                raw?.phone_number ||
                raw?.number ||
                raw?.cid ||
                node.id;

            const isTarget =
              raw?.is_target === true ||
              raw?.type === "target" ||
              raw?.role === "target" ||
              node.id === String(targetNumber);

            return (
              <g key={node.id}>
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={isTarget ? 13 : 9}
                  className={
                    isTarget
                      ? "cdr-network-node target"
                      : "cdr-network-node"
                  }
                >
                  <title>{String(label)}</title>
                </circle>

                <text
                  x={node.x}
                  y={node.y + 25}
                  className="cdr-network-node-label"
                  textAnchor="middle"
                >
                  {String(label).length > 16
                    ? `${String(label).slice(0, 13)}...`
                    : String(label)}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <div className="cdr-network-legend">
        <span>
          <i className="cdr-network-legend-dot target-dot" />
          Target, if identified in the data
        </span>
        <span>
          <i className="cdr-network-legend-line" />
          Communication link
        </span>
      </div>

      {graph.positionedEdges.length === 0 && edges.length > 0 && (
        <p className="cdr-network-note">
          The links could not be matched to the node IDs. Check the
          source and target fields returned by the backend.
        </p>
      )}
    </section>
  );
}
