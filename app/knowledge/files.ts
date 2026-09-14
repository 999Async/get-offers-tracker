export type KnowledgeFile = {
  documentId: string;
  versionId: string;
  label: string;
  filename: string;
};

export type KnowledgeDocument = {
  document_id: string;
  name: string;
  status: string;
  active_version?: string;
  versions: { version_id: string; extension: string; created_at: string }[];
};

export function knowledgeFiles(documents: KnowledgeDocument[]): KnowledgeFile[] {
  return documents.filter((doc) => !["deleting", "deleted"].includes(doc.status)).flatMap((doc) =>
    doc.versions.map((version, index) => {
      const filename = `${doc.name.replace(/\.[^.]+$/, "")}.${version.extension}`;
      return {
        documentId: doc.document_id,
        versionId: version.version_id,
        filename,
        label: `${filename} · 版本 ${doc.versions.length - index}`,
      };
    }),
  );
}

export type ResumeReference = {
  resume: string;
  resumeDocumentId: string;
  resumeVersionId: string;
};
