
import React, { useMemo } from "react";
import "./relationship-network.css";

function getNodeId(node, index) {
  return String(
    node?.id ??
    node?.cid ??
    node?.person_id ??
    node?.name ??
    `node-${index}`
  );
}

function getEndpointId(endpoint) {
  if (endpoint && typeof endpoint === "object") {
    return String(
      endpoint.id ??
      endpoint.cid ??
      endpoint.person_id ??
      endpoint.name ??
      ""
    );
  }

  return String(endpoint ?? "");
}

function getEdgeEndpoints(edge) {
  return {
    source: getEndpointId(
      edge.source ?? edge.from ?? edge.source_id
    ),
    target: getEndpointId(
      edge.target ?? edge.to ?? edge.target_id
    ),
  };
}

function getDegree(node, targetCid) {
  if (
    node?.relationship === "TARGET" ||
    (targetCid && String(node?.cid) === String(targetCid))
  ) {
    return 0;
  }

  if (node?.degree != null) {
    const degree = Number(node.degree);
    if ([1, 2, 3].includes(degree)) return degree;
  }

  const relationship = String(node?.relationship ?? "").toUpperCase();

  const degreeByRelationship = {
    SPOUSE: 1,
    CHILD: 1,
    PARENT: 2,
    SIBLING: 2,
    SIBLING_SPOUSE: 3,
    SIBLING_CHILD: 3,
  };

  return degreeByRelationship[relationship] ?? 1;
}

export default function RelationshipNetwork({ data }) {
  const nodes = Array.isArray(data?.nodes) ? data.nodes : [];
  const edges = Array.isArray(data?.edges) ? data.edges : [];
  const targetCid = data?.target?.cid
    ? String(data.target.cid)
    : "";

  const graph = useMemo(() => {
    const width = 900;
    const height = 650;
    const centerX = width / 2;
    const centerY = height / 2;

    const ringRadii = {
      1: 125,
      2: 220,
      3: 300,
    };

    const targetIndex = nodes.findIndex(
      (node) =>
         targetCid &&
         String(node?.cid ?? node?.id) === targetCid
    );

    const positionedNodes = nodes.map((node, index) => {
      const id = getNodeId(node, index);
      const degree = getDegree(node, targetCid);
      const isTarget =
        (targetCid &&
          String(node?.cid ?? node?.id) === targetCid) ||
        (targetIndex === -1 &&
          node?.relationship === "TARGET");

      if (isTarget) {
        return {
          raw: node,
          id,
          degree: 0,
          isTarget: true,
          x: centerX,
          y: centerY,
        };
      }

      const degreeNodes = nodes
        .map((candidate, candidateIndex) => ({
          candidate,
          candidateIndex,
          degree: getDegree(candidate, targetCid),
        }))
        .filter(
          (item) =>
            item.degree === degree &&
            item.candidateIndex !== targetIndex &&
            item.candidate?.relationship !== "TARGET"
        );

      const positionIndex = degreeNodes.findIndex(
        (item) => item.candidateIndex === index
      );

      const angle =
        (2 * Math.PI * Math.max(positionIndex, 0)) /
          Math.max(degreeNodes.length, 1) -
        Math.PI / 2;

      const radius = ringRadii[degree] ?? ringRadii[3];

      return {
        raw: node,
        id,
        degree,
        isTarget: false,
        x: centerX + radius * Math.cos(angle),
        y: centerY + radius * Math.sin(angle),
      };
    });

    // Index nodes by both ID and CID so API edges can use either.
    const nodeMap = new Map();

    positionedNodes.forEach((node) => {
      nodeMap.set(node.id, node);

      if (node.raw?.cid != null) {
        nodeMap.set(String(node.raw.cid), node);
      }
    });

    const positionedEdges = edges
      .map((edge, index) => {
        const endpoints = getEdgeEndpoints(edge);
        const sourceNode = nodeMap.get(endpoints.source);
        const targetNode = nodeMap.get(endpoints.target);

        if (
          !sourceNode ||
          !targetNode ||
          sourceNode === targetNode
        ) {
          return null;
        }

        return {
          ...edge,
          id: `relationship-edge-${index}`,
          sourceNode,
          targetNode,
        };
      })
      .filter(Boolean);

    return {
      width,
      height,
      positionedNodes,
      positionedEdges,
    };
  }, [nodes, edges, targetCid]);

  if (!nodes.length) {
    return (
      <div className="relationship-network-empty">
        No family-tree data is available.
      </div>
    );
  }

  const degreeCounts = [1, 2, 3].map((degree) => ({
    degree,
    count: graph.positionedNodes.filter(
      (node) => node.degree === degree && !node.isTarget
    ).length,
  }));

  return (
    <section className="relationship-network">
      <div className="relationship-network-heading">
        <div>
          <h3>Family Relationship Network</h3>
          <p>
            The target is at the center. Each ring represents
            a different relationship degree.
          </p>
        </div>

        <div className="relationship-network-stats">
          <span>{nodes.length} people</span>
          <span>{graph.positionedEdges.length} connections</span>
        </div>
      </div>

      <div className="relationship-network-canvas">
        <svg
          viewBox={`0 0 ${graph.width} ${graph.height}`}
          role="img"
          aria-label="Family relationship network"
        >
          {/* Degree rings */}
          {[3, 2, 1].map((degree) => (
            <circle
              key={`ring-${degree}`}
              cx={graph.width / 2}
              cy={graph.height / 2}
              r={degree === 1 ? 125 : degree === 2 ? 220 : 300}
              className={`relationship-network-ring degree-${degree}`}
            />
          ))}

          {/* Connections between relatives */}
          {graph.positionedEdges.map((edge) => (
            <g key={edge.id}>
              <line
                x1={edge.sourceNode.x}
                y1={edge.sourceNode.y}
                x2={edge.targetNode.x}
                y2={edge.targetNode.y}
                className={`relationship-network-edge degree-${edge.degree ?? edge.sourceNode.degree}`}
              >
                <title>
                  {edge.sourceNode.raw?.name ?? edge.sourceNode.id}
                  {" — "}
                  {edge.relationship ?? "Related to"}
                  {" — "}
                  {edge.targetNode.raw?.name ?? edge.targetNode.id}
                </title>
              </line>
            </g>
          ))}

          {/* People */}
          {graph.positionedNodes.map((node) => {
            const raw = node.raw;
            const name = String(
              raw?.name ?? raw?.full_name ?? "Unknown"
            );
            const cid = String(raw?.cid ?? node.id);

            const displayName =
              name.length > 20
                ? `${name.slice(0, 17)}...`
                : name;

            const displayCid =
              cid.length > 15
                ? `${cid.slice(0, 12)}...`
                : cid;

            return (
              <g
                key={node.id}
                className="relationship-network-person"
              >
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={node.isTarget ? 19 : 12}
                  className={
                    node.isTarget
                      ? "relationship-network-node target"
                      : `relationship-network-node degree-${node.degree}`
                  }
                >
                  <title>
                    {name}
                    {cid ? ` (CID: ${cid})` : ""}
                    {!node.isTarget
                      ? ` — Degree ${node.degree}`
                      : " — Target"}
                  </title>
                </circle>

                <text
                  x={node.x}
                  y={node.y + (node.isTarget ? 34 : 26)}
                  className="relationship-network-node-label"
                  textAnchor="middle"
                >
                  {displayName}
                </text>

                <text
                  x={node.x}
                  y={node.y + (node.isTarget ? 48 : 39)}
                  className="relationship-network-cid-label"
                  textAnchor="middle"
                >
                  {displayCid}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <div className="relationship-network-legend">
        <span>
          <i className="relationship-network-legend-dot target-dot" />
          Target
        </span>
        {degreeCounts.map(({ degree, count }) => (
          <span key={degree}>
            <i
              className={`relationship-network-legend-dot degree-${degree}`}
            />
            Degree {degree} ({count})
          </span>
        ))}
      </div>

      {graph.positionedEdges.length === 0 && edges.length > 0 && (
        <p className="relationship-network-note">
          Connections were returned by the API, but their endpoints
          could not be matched to the people in the graph. Check the
          node IDs and edge source/target values.
        </p>
      )}
    </section>
  );
}
