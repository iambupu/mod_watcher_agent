import React from "react";

interface RuleEditorLayoutProps {
  children: React.ReactNode;
}

export const RuleEditorLayout: React.FC<RuleEditorLayoutProps> = ({ children }) => {
  return (
    <div className="flex flex-col gap-4 container max-w-3xl mx-auto p-4">
      {children}
    </div>
  );
};
