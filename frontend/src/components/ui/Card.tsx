import React from "react";

interface CardProps {
  className?: string;
  children: React.ReactNode;
  onClick?: () => void;
}

export const Card: React.FC<CardProps> = ({ className = "", children, onClick }) => {
  return (
    <div
      className={`rounded-lg border border-gray-200 bg-white shadow-sm ${onClick ? "cursor-pointer hover:shadow-md transition-shadow" : ""} ${className}`}
      onClick={onClick}
    >
      {children}
    </div>
  );
};

interface CardHeaderProps {
  className?: string;
  children: React.ReactNode;
}

export const CardHeader: React.FC<CardHeaderProps> = ({ className = "", children }) => {
  return <div className={`px-4 py-3 border-b border-gray-100 ${className}`}>{children}</div>;
};

interface CardContentProps {
  className?: string;
  children: React.ReactNode;
}

export const CardContent: React.FC<CardContentProps> = ({ className = "", children }) => {
  return <div className={`px-4 py-3 ${className}`}>{children}</div>;
};
